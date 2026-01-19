import os
import json
import time
import logging
import re
from google import genai
from google.genai import types
from agentic_consult.config import get_default_model, resolve_model_alias, load_app_config

logger = logging.getLogger(__name__)

class GeminiOutputError(Exception):
    """Base class for all Gemini output errors."""
    pass

class GeminiJSONExtractionError(GeminiOutputError):
    """Raised when no JSON-like content could be found in the response."""
    pass

class GeminiJSONParseError(GeminiOutputError):
    """Raised when text (either raw or extracted) failed to parse as JSON."""
    pass

class GeminiSchemaValidationError(GeminiOutputError):
    """Raised when the parsed JSON does not match the required schema."""
    pass

def clean_json_output(content: str) -> str:
    """
    Cleans LLM output to extract just the JSON content.
    Removes markdown code blocks and any preamble/postscript text.
    Raises GeminiJSONExtractionError if no candidate JSON is found.
    """
    content = content.strip()
    
    # 1. Strip Markdown code blocks
    if "```" in content:
        # Match content inside ```json ... ``` or just ``` ... ```
        match = re.search(r'```(?:\w+)?\s*(.*?)\s*```', content, re.DOTALL)
        if match:
            content = match.group(1)
            
    # 2. Find the first '{' and last '}' to handle any remaining preamble
    start_idx = content.find('{')
    end_idx = content.rfind('}')
    
    if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
        return content[start_idx : end_idx + 1]
        
    raise GeminiJSONExtractionError("No recognizable JSON structure found in response.")

class GeminiAPIClient:
    def __init__(self, api_key=None, model_name=None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        
        # Fallback to app config
        if not self.api_key:
            app_config = load_app_config()
            self.api_key = app_config.get("gemini", {}).get("api_key")

        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in environment, arguments, or app configuration.")
        
        raw_model = model_name or get_default_model()
        self.model_name = resolve_model_alias(raw_model)
        self.client = genai.Client(api_key=self.api_key)

    def _tweak_prompt(self, prompt: str) -> str:
        """Applies GEMINI_TWEAK_PROMPT_REGEX if set."""
        tweak = os.environ.get("GEMINI_TWEAK_PROMPT_REGEX")
        if not tweak or not tweak.startswith('s/'):
            return prompt
            
        try:
            # Simple s/pattern/replacement/ parser
            parts = tweak.split('/')
            if len(parts) >= 3:
                pattern = parts[1]
                replacement = parts[2]
                return re.sub(pattern, replacement, prompt)
        except Exception as e:
            logger.warning(f"Failed to apply prompt tweak: {e}")
            
        return prompt

    def generate_content(self, contents, generation_config=None, tools=None, tool_config=None):
        """
        Generates content using the google-genai SDK.
        """
        if isinstance(contents, str):
            contents = self._tweak_prompt(contents)
        
        logger.debug(f"Gemini request - model={self.model_name}, prompt_length={len(contents) if isinstance(contents, str) else 'N/A'}")
        logger.debug(f"Gemini full prompt:\n{contents}")
        start_time = time.time()
        
        config_kwargs = {}
        if generation_config:
            config_kwargs.update(generation_config)
        
        if tools:
            config_kwargs['tools'] = tools
            
        if tool_config:
            config_kwargs['tool_config'] = tool_config

        config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config
            )
            duration = time.time() - start_time
            logger.debug(f"Gemini response - latency={duration:.2f}s")
            logger.debug(f"Gemini full response:\n{response.text}")
            
            return {
                "text": response.text,
                "latency": duration,
                "raw_response": response,
                "function_calls": response.function_calls if hasattr(response, 'function_calls') else None
            }
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"API execution failed after {duration:.2f}s: {e}")
            raise

    def generate_prompt_driven_json(self, contents, generation_config=None, schema=None):
        """
        Operation 1: Basic Prompt-Driven JSON.
        """
        result = self.generate_content(contents, generation_config)
        text = result["text"]
        
        # Determine candidate string
        if os.environ.get("GEMINI_DISABLE_JSON_SCRUBBING", "").lower() == "true":
            candidate_json = text
        else:
            try:
                candidate_json = clean_json_output(text)
            except GeminiJSONExtractionError:
                raise

        # Parsing
        try:
            data = json.loads(candidate_json)
        except json.JSONDecodeError as e:
            raise GeminiJSONParseError(f"Failed to parse JSON: {e}")

        # Validation
        if schema:
            import jsonschema
            try:
                # Handle pydantic models if passed as schema
                if hasattr(schema, 'model_json_schema'):
                    jsonschema.validate(data, schema.model_json_schema())
                else:
                    jsonschema.validate(data, schema)
            except jsonschema.ValidationError as e:
                raise GeminiSchemaValidationError(f"Schema validation failed: {e}")

        return data

    def generate_schema_driven_json(self, contents, schema):
        """
        Operation 2: Schema-Driven JSON.
        Uses the SDK's response_schema capability to enforce strict adherence to a structure.
        """
        config = {
            "response_mime_type": "application/json",
            "response_schema": schema
        }
        
        result = self.generate_content(contents, generation_config=config)
        return json.loads(result["text"])

    def generate_with_function_calls_prepared(self, contents, tools, tool_config=None):
        """
        Operation 3: Manual Function Calling (Prepared).
        The model analyzes the prompt and prepares suggested function calls (name and arguments) 
        without executing them.
        """
        return self.generate_content(contents, tools=tools, tool_config=tool_config)

    def generate_with_function_calls_executed(self, contents, tools, tool_config=None):
        """
        Operation 4: Automatic Function Calling (Executed).
        The SDK automatically executes the suggested tools and uses the results 
        to generate the final text response.
        """
        config = types.GenerateContentConfig(
            tools=tools,
            tool_config=tool_config
        )
        
        chat = self.client.chats.create(model=self.model_name, config=config)
        
        start_time = time.time()
        response = chat.send_message(contents)
        duration = time.time() - start_time
        
        return {
            "text": response.text,
            "latency": duration,
            "raw_response": response
        }
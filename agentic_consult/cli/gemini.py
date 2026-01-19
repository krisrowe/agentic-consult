import click
import sys
import logging
import os
from typing import List
from agentic_consult.gemini import GeminiAPIClient
from agentic_consult.config import get_model_help_text, load_app_config
from agentic_consult.context import build_context

# Configure Logging
log_level_str = os.environ.get("LOG_LEVEL", "WARNING").upper()
log_level = getattr(logging, log_level_str, logging.WARNING)

class PlainInfoFormatter(logging.Formatter):
    def format(self, record):
        if record.levelno == logging.INFO:
            return record.getMessage()
        return f"{record.levelname}: {record.getMessage()}"

handler = logging.StreamHandler(sys.stderr)
handler.setFormatter(PlainInfoFormatter())
logging.basicConfig(level=log_level, handlers=[handler], force=True)
logger = logging.getLogger(__name__)

@click.command()
@click.argument("prompt")
@click.argument("context_paths", nargs=-1, type=click.Path(exists=True))
@click.option("--exclude", "-e", multiple=True, help="Exclusion patterns (pathspec/gitignore style).")
@click.option("--max-text-size", type=int, help="Max size for text files in KB. Default: From app.yaml.")
@click.option("--max-binary-size", type=int, help="Max size for binary files in KB. Default: From app.yaml.")
@click.option(
    "--on-limit", 
    type=click.Choice(["skip", "warn", "fail"]),
    default="warn", 
    help="Action when a file exceeds max-size. Default: warn."
)
@click.option("--model", "-m", help=f"Override the Gemini model. {get_model_help_text()}")
@click.option("--stats", "-s", "stats_enabled", is_flag=True, help="Show execution statistics.")
def gemini(prompt, context_paths, exclude, max_text_size, max_binary_size, on_limit, model, stats_enabled):
    """
    Directly query the Gemini API with a prompt and optional context.
    
    If PROMPT is '-', the prompt is read from stdin.
    CONTEXT_PATHS can be files or directories to include in the prompt.
    """
    if prompt == "-":
        prompt = sys.stdin.read()

    # Callback for warnings
    def warn(msg):
        click.echo(msg, err=True)

    # Resolve Limits
    app_config = load_app_config()
    analyze_cfg = app_config.get('analyze', {})
    final_text_limit = max_text_size or analyze_cfg.get('max_text_size_kb', 100)
    final_binary_limit = max_binary_size or analyze_cfg.get('max_binary_size_kb', 20480)

    try:
        # Collect Context
        context_items = build_context(
            context_paths, 
            exclude, 
            max_text_size_kb=final_text_limit,
            max_binary_size_kb=final_binary_limit,
            on_limit=on_limit,
            warning_callback=warn
        )

        # Build Contents List
        client = GeminiAPIClient(model_name=model)
        contents = []
        text_context = []
        binary_items = []

        for item in context_items:
            if item.is_binary:
                # Upload binary file
                try:
                    logger.debug(f"Uploading file: {item.header_path}")
                    uploaded_file = client.client.files.upload(file=str(item.path))
                    contents.append(uploaded_file)
                    binary_items.append(item)
                except Exception as e:
                    warn(f"Warning: Failed to upload binary file {item.header_path}: {e}")
            else:
                text_context.append(f"--- File: {item.header_path} ---\n{item.content}\n")

        # Combine text context and prompt
        full_text_prompt = prompt
        if text_context:
            full_text_prompt = f"Context:\n\n{''.join(text_context)}\n\nQuestion: {prompt}"
        
        contents.append(full_text_prompt)
        
        # Calculate Sizes
        prompt_bytes = len(full_text_prompt.encode('utf-8'))
        def format_size(bytes_val):
            if bytes_val < 1024: return f"{bytes_val} bytes"
            if bytes_val < 1024 * 1024: return f"{bytes_val / 1024:.2f} KB"
            return f"{bytes_val / (1024 * 1024):.2f} MB"

        text_size_str = format_size(prompt_bytes)
        logger.debug(f"Total Text Prompt Size: {text_size_str}")

        binary_total_bytes = sum(item.path.stat().st_size for item in binary_items)
        binary_size_str = format_size(binary_total_bytes)
        
        # Summary Info
        files_count = len(binary_items)
        prompt_preview = (prompt[:50] + '...') if len(prompt) > 50 else prompt
        logger.info(f"Sending prompt to Gemini ({client.model_name}): \"{prompt_preview}\" | {text_size_str} of text, {files_count} files of {binary_size_str} total")

        # Call Gemini
        result = client.generate_content(contents)
        
        if stats_enabled:
            resp_text = result["text"]
            click.echo(f"--- Execution Stats ---", err=True)
            click.echo(f"Model: {client.model_name}", err=True)
            click.echo(f"Latency: {result['latency']:.2f}s", err=True)
            click.echo(f"Input Text Size: {len(full_text_prompt)} chars", err=True)
            click.echo(f"Output Size: {len(resp_text)} chars", err=True)
            if text_context:
                click.echo(f"Text Context Files: {len(text_context)}", err=True)
            if binary_items:
                click.echo(f"Binary Files Uploaded: {len(binary_items)}", err=True)
            click.echo(f"------------------------", err=True)

        click.echo(result["text"])

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
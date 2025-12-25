import re
import json

DATE_PREFIX_RE = re.compile(r'^\d{2}-\d{2}-\d{2}_')

def is_drive_id_candidate(token):
    """
    Heuristic: A Drive ID should be 20-70 chars, mixed case/digits.
    Must NOT look like a date-prefixed filename (YY-MM-DD_...).
    """
    if not token or not (20 <= len(token) <= 70):
        return False
    # Must contain at least one digit and one letter
    if not re.search(r'\d', token) or not re.search(r'[A-Za-z]', token):
        return False
    # Explicitly ignore tokens starting with date pattern (issue filenames)
    if DATE_PREFIX_RE.match(token):
        return False
    return True

def clean_json_output(content: str) -> str:
    """
    Cleans LLM output to extract just the JSON content.
    Removes markdown code blocks and any preamble/postscript text.
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
    
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        content = content[start_idx : end_idx + 1]
        
    return content

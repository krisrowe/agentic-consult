import shutil
from pathlib import Path
from agentic_consult.gemini import GeminiAPIClient
from agentic_consult.paths import get_settings_dir

def resolve_context_path(scope: str) -> Path:
    """Resolves the path to the GEMINI.md file based on scope."""
    if scope == "project":
        target_path = Path.cwd() / ".gemini" / "GEMINI.md"
        # Fallback for some project structures
        if not target_path.exists():
            target_path = Path.cwd() / "GEMINI.md"
    else: # user
        target_path = get_settings_dir() / "GEMINI.md"

    return target_path

def analyze_context(scope: str, prompt: str, model: str = None) -> str:
    """
    Analyzes the context file using an LLM.
    Returns the analysis text.
    """
    target_path = resolve_context_path(scope)
    
    if not target_path.exists():
        raise FileNotFoundError(f"Context file not found at {target_path}")

    content = target_path.read_text(encoding="utf-8")

    analysis_instruction = (
        "You are an expert technical writer and configuration manager.\n"
        "Your task is to answer the user's question based on the provided Context File.\n"
        "\n"
        "--- CONTEXT FILE CONTENT ---\n"
        f"{content}\n"
        "--- END CONTEXT FILE CONTENT ---\n"
        "\n"
        f"USER QUESTION: {prompt}"
    )

    client = GeminiAPIClient(model_name=model)
    result = client.generate_content(analysis_instruction)
    return result["text"]

def revise_context(scope: str, prompt: str, model: str = None) -> str:
    """
    Revises the context file using an LLM.
    Backs up the original file before overwriting.
    Returns the success message.
    """
    target_path = resolve_context_path(scope)
    
    if not target_path.exists():
        raise FileNotFoundError(f"Context file not found at {target_path}")

    original_content = target_path.read_text(encoding="utf-8")

    revision_instruction = (
        "You are an expert technical writer and configuration manager.\n"
        "Your task is to update the following Context File based on the user's request.\n"
        "Strictly adhere to these rules:\n"
        "1. Return ONLY the full content of the updated file. No markdown code blocks, no intro/outro text.\n"
        "2. Preserve all existing sections, formatting, and content unless the user's request specifically implies changing them.\n"
        "3. Ensure the result is valid Markdown.\n"
        "\n"
        "--- CURRENT FILE CONTENT ---\n"
        f"{original_content}\n"
        "--- END CURRENT FILE CONTENT ---\n"
        "\n"
        f"USER REQUEST: {prompt}"
    )

    client = GeminiAPIClient(model_name=model)
    result = client.generate_content(revision_instruction)
    new_content = result["text"]
    
    # Strip potential markdown code blocks
    if new_content.startswith("```markdown"):
        new_content = new_content[11:]
    elif new_content.startswith("```"):
        new_content = new_content[3:]
    
    if new_content.endswith("```"):
        new_content = new_content[:-3]
    
    new_content = new_content.strip()

    # Backup and Write
    backup_path = target_path.with_suffix(".md.bak")
    shutil.copy2(target_path, backup_path)
    target_path.write_text(new_content, encoding="utf-8")
    
    return f"Successfully revised {target_path} (Backup: {backup_path})"

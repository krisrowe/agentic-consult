import click
import shutil
import sys
from pathlib import Path
from agentic_consult.gemini import GeminiAPIClient
from agentic_consult.config import get_model_help_text

@click.group()
def context():
    """Manage Gemini context files (GEMINI.md)."""
    pass

@context.command()
@click.argument("prompt")
@click.option(
    "--scope", 
    type=click.Choice(["project", "user"]),
    default="project",
    help="Scope of the context file to revise."
)
@click.option("--model", "-m", help=f"Override the Gemini model. {get_model_help_text()}")
def revise(prompt, scope, model):
    """
    Revise the GEMINI.md context file using an LLM.

    Reads the existing GEMINI.md (based on scope), sends it to Gemini
    with your revision prompt, and overwrites the file with the result.
    A backup (.bak) is created before overwriting.
    """
    
    # 1. Resolve Path
    if scope == "project":
        target_path = Path.cwd() / ".gemini" / "GEMINI.md"
        # Fallback for some project structures
        if not target_path.exists():
            target_path = Path.cwd() / "GEMINI.md"
            
    else: # user
        target_path = Path.home() / ".config" / "agentic-consult" / "GEMINI.md"

    if not target_path.exists():
        click.echo(f"Error: Context file not found at {target_path}", err=True)
        sys.exit(1)

    # 2. Read Content
    try:
        original_content = target_path.read_text(encoding="utf-8")
    except Exception as e:
        click.echo(f"Error reading {target_path}: {e}", err=True)
        sys.exit(1)

    # 3. Construct Prompt
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

    # 4. Call Gemini
    try:
        click.echo(f"Consulting Gemini to revise {target_path}...", err=True)
        client = GeminiAPIClient(model_name=model)
        result = client.generate_content(revision_instruction)
        new_content = result["text"]
        
        # Strip potential markdown code blocks if the model disobeyed
        if new_content.startswith("```markdown"):
            new_content = new_content[11:]
        elif new_content.startswith("```"):
            new_content = new_content[3:]
        
        if new_content.endswith("```"):
            new_content = new_content[:-3]
        
        new_content = new_content.strip()

    except Exception as e:
        click.echo(f"Error calling Gemini: {e}", err=True)
        sys.exit(1)

    # 5. Backup and Write
    backup_path = target_path.with_suffix(".md.bak")
    try:
        shutil.copy2(target_path, backup_path)
        click.echo(f"Backup created at {backup_path}", err=True)
        
        target_path.write_text(new_content, encoding="utf-8")
        click.echo(f"Successfully revised {target_path}", err=True)
    except Exception as e:
        click.echo(f"Error writing file: {e}", err=True)
        sys.exit(1)

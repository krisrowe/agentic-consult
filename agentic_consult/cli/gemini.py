import click
import sys
import os
import pathspec
from pathlib import Path
from typing import List, Optional
from agentic_consult.gemini import GeminiAPIClient
from agentic_consult.config import get_model_help_text

def is_binary(path: Path) -> bool:
    """Detect binary files using the null-byte heuristic (first 8KB)."""
    try:
        with open(path, 'rb') as f:
            chunk = f.read(8192)
            return b'\x00' in chunk
    except Exception:
        return True # Treat as binary if we can't read it

def process_file(
    path: Path, 
    spec: pathspec.PathSpec, 
    max_size_kb: int, 
    on_limit: str,
    header_path: str
) -> Optional[str]:
    """Checks and reads a single file, returning its formatted content for the prompt."""
    # 1. Check Exclusions
    if spec.match_file(header_path):
        return None

    # 2. Check if file exists and is a file
    if not path.is_file():
        return None

    # 3. Check Binary
    if is_binary(path):
        return None

    # 4. Check Size
    size_kb = path.stat().st_size / 1024
    if size_kb > max_size_kb:
        msg = f"File {header_path} exceeds size limit ({size_kb:.1f}KB > {max_size_kb}KB)."
        if on_limit == "fail":
            click.echo(f"Error: {msg}", err=True)
            sys.exit(1)
        elif on_limit == "warn":
            click.echo(f"Warning: {msg} Skipping.", err=True)
            return None
        else: # skip
            return None

    # 5. Read Content
    try:
        content = path.read_text(encoding='utf-8')
        return f"--- File: {header_path} ---\n{content}\n"
    except Exception as e:
        click.echo(f"Warning: Could not read {header_path}: {e}", err=True)
        return None

@click.command()
@click.argument("prompt")
@click.argument("context_paths", nargs=-1, type=click.Path(exists=True))
@click.option("--exclude", "-e", multiple=True, help="Exclusion patterns (pathspec/gitignore style).")
@click.option("--max-size", type=int, default=100, help="Max size per file in KB. Default: 100KB.")
@click.option(
    "--on-limit", 
    type=click.Choice(["skip", "warn", "fail"]),
    default="warn", 
    help="Action when a file exceeds max-size. Default: warn."
)
@click.option("--model", "-m", help=f"Override the Gemini model. {get_model_help_text()}")
@click.option("--stats", "-s", "stats_enabled", is_flag=True, help="Show execution statistics.")
def gemini(prompt, context_paths, exclude, max_size, on_limit, model, stats_enabled):
    """
    Directly query the Gemini API with a prompt and optional context.
    
    If PROMPT is '-', the prompt is read from stdin.
    CONTEXT_PATHS can be files or directories to include in the prompt.
    """
    if prompt == "-":
        prompt = sys.stdin.read()

    # 1. Build Exclusion Spec
    spec = pathspec.PathSpec.from_lines('gitwildmatch', exclude)

    # 2. Collect Context Content
    context_chunks = []
    cwd = Path.cwd()
    
    for entry in context_paths:
        p = Path(entry)
        if p.is_file():
            # Use relative path for spec check and header if it's under CWD
            try:
                rel_path = p.relative_to(cwd)
                header = str(rel_path)
            except ValueError:
                header = str(p)
            
            chunk = process_file(p, spec, max_size, on_limit, header)
            if chunk:
                context_chunks.append(chunk)
        elif p.is_dir():
            # Walk directory recursively
            for root, dirs, files in os.walk(p):
                # Ensure we have a path object for the current root
                root_path = Path(root)
                try:
                    rel_root = root_path.relative_to(cwd)
                except ValueError:
                    rel_root = root_path
                
                # Filter directories in-place for os.walk performance
                dirs[:] = [d for d in dirs if not spec.match_file(str(rel_root / d))]
                
                for file in files:
                    file_path = root_path / file
                    try:
                        rel_file = file_path.relative_to(cwd)
                        header = str(rel_file)
                    except ValueError:
                        header = str(file_path)
                        
                    chunk = process_file(file_path, spec, max_size, on_limit, header)
                    if chunk:
                        context_chunks.append(chunk)

    # 3. Build Final Prompt
    full_prompt = prompt
    if context_chunks:
        full_prompt = f"Context:\n\n{''.join(context_chunks)}\n\nQuestion: {prompt}"

    # 4. Call Gemini
    try:
        client = GeminiAPIClient(model_name=model)
        result = client.generate_content(full_prompt)
        
        if stats_enabled:
            resp_text = result["text"]
            click.echo(f"--- Execution Stats ---", err=True)
            click.echo(f"Model: {client.model_name}", err=True)
            click.echo(f"Latency: {result['latency']:.2f}s", err=True)
            click.echo(f"Input Size: {len(full_prompt)} chars", err=True)
            click.echo(f"Output Size: {len(resp_text)} chars", err=True)
            if context_chunks:
                click.echo(f"Context Files: {len(context_chunks)}", err=True)
            click.echo(f"------------------------", err=True)

        click.echo(result["text"])
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

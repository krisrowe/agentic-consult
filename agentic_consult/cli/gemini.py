import click
import sys
from typing import List
from agentic_consult.gemini import GeminiAPIClient
from agentic_consult.config import get_model_help_text
from agentic_consult.context import build_context

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

    # Callback for warnings
    def warn(msg):
        click.echo(msg, err=True)

    try:
        # Collect Context
        context_chunks = build_context(
            context_paths, 
            exclude, 
            max_size_kb=max_size, 
            on_limit=on_limit,
            warning_callback=warn
        )

        # Build Final Prompt
        full_prompt = prompt
        if context_chunks:
            full_prompt = f"Context:\n\n{''.join(context_chunks)}\n\nQuestion: {prompt}"

        # Call Gemini
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
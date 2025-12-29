import click
import sys
from agentic_consult.gemini import GeminiAPIClient
from agentic_consult.config import get_model_help_text

@click.command()
@click.argument("prompt")
@click.option("--model", "-m", help=f"Override the Gemini model. {get_model_help_text()}")
@click.option("--stats", "-s", "stats_enabled", is_flag=True, help="Show execution statistics.")
def gemini(prompt, model, stats_enabled):
    """
    Directly query the Gemini API with a prompt.
    
    If PROMPT is '-', the prompt is read from stdin.
    """
    if prompt == "-":
        prompt = sys.stdin.read()
    
    try:
        client = GeminiAPIClient(model_name=model)
        result = client.generate_content(prompt)
        
        if stats_enabled:
            resp_text = result["text"]
            click.echo(f"--- Execution Stats ---", err=True)
            click.echo(f"Model: {client.model_name}", err=True)
            click.echo(f"Latency: {result['latency']:.2f}s", err=True)
            click.echo(f"Input Size: {len(prompt)} chars", err=True)
            click.echo(f"Output Size: {len(resp_text)} chars", err=True)
            click.echo(f"------------------------", err=True)

        click.echo(result["text"])
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
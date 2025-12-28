import click
import json
from agentic_consult.config import get_model_configuration

@click.group()
def models():
    """Manage and view Gemini model configuration."""
    pass

@models.command(name="list")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def list_models(json_output):
    """List available models, aliases, and defaults."""
    config = get_model_configuration()
    
    if json_output:
        click.echo(json.dumps(config, indent=2))
        return

    click.echo("\n=== Gemini Model Configuration ===\n")
    
    # 1. Available Models
    click.echo("Available Models (Priority Order):")
    default_model = config.get('default')
    for model in config.get('available', []):
        marker = " (Default)" if model == default_model else ""
        click.echo(f"  - {model}{marker}")
    
    click.echo("")
    
    # 2. Alias Resolutions
    click.echo("Alias Resolutions:")
    resolutions = config.get('resolutions', {})
    for alias, target in resolutions.items():
        click.echo(f"  - {alias:<10} -> {target}")
    
    click.echo("")


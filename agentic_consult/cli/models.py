import click
import json
from agentic_consult.config import (
    get_model_configuration, 
    resolve_model_alias, 
    load_main_config, 
    save_main_config,
    parse_model_version
)

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
    click.echo("Available Models:")
    default_model = config.get('default')
    for model in config.get('available', []):
        is_stable, _, _ = parse_model_version(model)
        status = "Stable" if is_stable else "Preview"
        
        markers = [f"({status})"]
        if model == default_model:
            markers.append("(Default)")
            
        click.echo(f"  - {model:<25} {' '.join(markers)}")
    
    click.echo("")
    
    # 2. Alias Resolutions
    click.echo("Alias Resolutions:")
    resolutions = config.get('resolutions', {})
    for alias, target in resolutions.items():
        click.echo(f"  - {alias:<10} -> {target} (Latest Stable)")
    
    click.echo("")

@models.command(name="set-default")
@click.argument("model")
def set_default(model):
    """
    Set the user-level default Gemini model.
    
    Accepts specific model IDs (e.g., gemini-2.5-flash) or aliases (fast, thinking).
    Aliases are resolved to their current target before saving.
    """
    config = get_model_configuration()
    available = config.get('available', [])
    
    # Resolve input (alias -> ID)
    resolved = resolve_model_alias(model)
    
    if resolved not in available:
        click.echo(f"Error: Model '{model}' (resolved: '{resolved}') is not in the available list.", err=True)
        click.echo(f"Available models: {', '.join(available)}", err=True)
        return

    # Load current settings, update, and save
    user_settings = load_main_config()
    if 'models' not in user_settings:
        user_settings['models'] = {}
        
    user_settings['models']['default'] = resolved
    
    save_main_config(user_settings)
    click.echo(f"Success: User default model set to '{resolved}'.")

@models.command(name="reset-default")
def reset_default():
    """
    Remove the user-level default model override.
    Reverts the system to its standard default configuration.
    """
    user_settings = load_main_config()
    
    if 'models' in user_settings:
        user_settings.pop('models')
        save_main_config(user_settings)
        
        # Get the new default for confirmation
        config = get_model_configuration()
        new_default = config.get('default')
        click.echo(f"Success: User default removed. System is now using '{new_default}'.")
    else:
        click.echo("No user default configured. Standard default is already active.")


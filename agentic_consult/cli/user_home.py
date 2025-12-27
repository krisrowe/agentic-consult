import click
from agentic_consult.config import load_main_config, save_main_config

@click.group(name='user-home')
def user_home_cli():
    """Manage user home backup configuration (dotfiles, etc.)."""
    pass

@user_home_cli.command(name='init-defaults')
def init_defaults():
    """
    Initializes default paths for user home backup in settings.json.
    Includes .gemini/settings.json, .gemini/GEMINI.md, and .config/agentic-consult/settings.json.
    """
    config_data = load_main_config()
    
    default_paths = [
        ".gemini/settings.json",
        ".gemini/GEMINI.md",
        ".config/agentic-consult/settings.json" # Backup its own config
    ]
    
    if 'backups' not in config_data or not isinstance(config_data['backups'], dict):
        config_data['backups'] = {}
    if 'user_home' not in config_data['backups'] or not isinstance(config_data['backups']['user_home'], dict):
        config_data['backups']['user_home'] = {}
        
    config_data['backups']['user_home']['paths'] = default_paths
    config_data['backups']['user_home']['enabled'] = True
    
    path = save_main_config(config_data)
    click.echo(f"Initialized default user home backup paths in {path}.")
    click.echo("Paths configured:")
    for p in default_paths:
        click.echo(f"  - {p}")

@user_home_cli.command(name='add')
@click.argument('path_to_add')
def add_path(path_to_add):
    """
    Adds a path (relative to HOME) to the user home backup list.
    Example: consult config user-home add .ssh/id_rsa
    """
    config_data = load_main_config()
    if 'backups' not in config_data: config_data['backups'] = {}
    if 'user_home' not in config_data['backups']: config_data['backups']['user_home'] = {}
    if 'paths' not in config_data['backups']['user_home']: config_data['backups']['user_home']['paths'] = []
    
    paths = config_data['backups']['user_home']['paths']
    if path_to_add not in paths:
        paths.append(path_to_add)
        save_main_config(config_data)
        click.echo(f"Added '{path_to_add}' to user home backup paths.")
    else:
        click.echo(f"Path '{path_to_add}' already exists in backup list.")

@user_home_cli.command(name='remove')
@click.argument('path_to_remove')
def remove_path(path_to_remove):
    """Removes a path from the user home backup list."""
    config_data = load_main_config()
    if 'backups' in config_data and 'user_home' in config_data['backups'] and \
       'paths' in config_data['backups']['user_home'] and \
       path_to_remove in config_data['backups']['user_home']['paths']:
        
        config_data['backups']['user_home']['paths'].remove(path_to_remove)
        save_main_config(config_data)
        click.echo(f"Removed '{path_to_remove}' from user home backup paths.")
    else:
        click.echo(f"Path '{path_to_remove}' not found in backup list.")

@user_home_cli.command(name='show')
def show_paths():
    """Shows currently configured user home backup paths."""
    config_data = load_main_config()
    user_home_config = config_data.get('backups', {}).get('user_home', {})
    paths = user_home_config.get('paths', [])
    enabled = user_home_config.get('enabled', True)
    
    click.echo(f"User Home Backup Enabled: {enabled}")
    if paths:
        click.echo("Configured paths (relative to HOME):")
        for p in paths:
            click.echo(f"  - {p}")
    else:
        click.echo("No user home backup paths configured.")


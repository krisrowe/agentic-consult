import click
import sys
from pathlib import Path
from agentic_consult.config import load_main_config, save_main_config, get_settings_dir

def get_default_user_home_config():
    """
    Returns the default configuration dictionary for user_home backups.
    Shared by 'init-defaults' and 'consult config init'.
    """
    # Calculate default tool config path (respects CONSULT_CONFIG_DIR for test isolation)
    default_settings_dir = get_settings_dir()
    try:
        relative_path = default_settings_dir.relative_to(Path.home())
        tool_config_path = str(relative_path)
    except ValueError:
        tool_config_path = str(default_settings_dir)

    default_paths = [
        # Gemini CLI
        ".gemini/settings.json",
        ".gemini/GEMINI.md",
        ".gemini/commands/",
        # Claude Code
        ".claude/settings.json",
        ".claude/CLAUDE.md",
        # Agentic Consult
        tool_config_path
    ]
    
    return {
        "enabled": True,
        "paths": default_paths
    }

@click.group(name='user-home')
def user_home_cli():
    """Manage user home backup configuration (dotfiles, etc.)."""
    pass

@user_home_cli.command(name='init')
def init_defaults():
    """
    Initializes default paths for user home backup in settings.json.
    Includes .gemini, .claude, and the tool's config directory.
    """
    config_data = load_main_config()
    defaults = get_default_user_home_config()
    
    if 'backups' not in config_data or not isinstance(config_data['backups'], dict):
        config_data['backups'] = {}
    if 'user_home' not in config_data['backups'] or not isinstance(config_data['backups']['user_home'], dict):
        config_data['backups']['user_home'] = {}
        
    # Apply defaults
    config_data['backups']['user_home']['paths'] = defaults['paths']
    config_data['backups']['user_home']['enabled'] = defaults['enabled']
    
    path = save_main_config(config_data)
    click.echo(f"Initialized default user home backup paths in {path}.")
    click.echo("Paths configured:")
    for p in defaults['paths']:
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

@user_home_cli.command(name='run')
@click.option('--non-interactive', is_flag=True, help="Disable interactive prompts.")
@click.option('--dry-run', is_flag=True, help="Simulate backup without uploading.")
def run_backup(non_interactive, dry_run):
    """Runs ONLY the User Home configuration backup."""
    from agentic_consult.backup.providers.user_home import UserHomeBackup
    from agentic_consult.backup.results import BackupStatus
    
    config_data = load_main_config()
    provider = UserHomeBackup()
    
    # Check if backup folder is configured
    from agentic_consult.config import get_backups_google_drive_folder_id
    if not get_backups_google_drive_folder_id():
        click.echo("Error: Backup folder not configured. Run 'consult backup config' first.", err=True)
        return

    options = {
        'interactive': sys.stdin.isatty() and not non_interactive,
        'dry_run': dry_run,
        'force': False,
        'skip_dirty': False
    }
    
    click.echo(f"Running {provider.name}...")
    result = provider.run(config_data, options)
    
    # Simple output
    if result.status == "skipped":
        click.echo(f"Skipped: {result.message}")
        return
        
    for item in result.items:
        status_icon = "✅" if item.status == BackupStatus.SUCCESS else \
                      "❌" if item.status == BackupStatus.FAILED else \
                      "ℹ️ " 
        click.echo(f"{status_icon} {item.name}: {item.message}")
    
    if result.status == "failure":
        click.echo(f"Backup failed: {result.message}", err=True)
        sys.exit(1)
    else:
        click.echo(f"\n{result.message}")


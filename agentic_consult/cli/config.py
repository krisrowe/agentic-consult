import click
import sys
import json
import yaml

from agentic_consult.customers import get_active_customers_root
from agentic_consult.config import load_main_config, save_main_config, get_config_path
from .user_home import user_home_cli


@click.group()
def config():
    """Manage global configuration."""
    pass

@config.command(name='show')
def config_show():
    """Show current configuration."""
    data = load_main_config()
    path = get_config_path()
    
    # Show resolved paths first
    root = get_active_customers_root()
    click.echo(f"# Global Settings: {path}")
    click.echo(f"# Active Customers Root: {root}")

    # Count customers
    customer_count = 0
    if root.exists():
        for d in root.iterdir():
            if d.is_dir() and (d / 'customer.yaml').exists():
                customer_count += 1
    click.echo(f"# Found {customer_count} customer(s).")

    if not data:
        click.echo("# No global settings.json found (using defaults).")
    else:
        click.echo(json.dumps(data, indent=2))

@config.command(name='set')
@click.argument('key')
@click.argument('value')
def config_set(key, value):
    """Set a configuration value. Supports dot-notation for nested keys.
    
    Examples:
      consult config set local_data /path/to/data
      consult config set backups.local_repos.enabled false
    """
    data = load_main_config()
    
    # Map legacy CLI keys to config keys
    key_map = {
        'local-data': 'local_data',
        'cloud-folder-id': 'google_drive_all_customers_folder_id',
        'customers-local-path': 'local_data'
    }
    
    real_key = key_map.get(key, key)
    
    # Handle boolean conversion
    if value.lower() == 'true':
        value = True
    elif value.lower() == 'false':
        value = False

    # Handle nested keys
    keys = real_key.split('.')
    current = data
    for k in keys[:-1]:
        if k not in current or not isinstance(current[k], dict):
            current[k] = {}
        current = current[k]
    
    current[keys[-1]] = value
    
    path = save_main_config(data)
    click.echo(f"Updated {real_key} in {path}")

config.add_command(user_home_cli)

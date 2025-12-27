import click
import sys
import json
import yaml

from agentic_consult.customers import get_active_customers_root
from agentic_consult.config import load_main_config, save_main_config, get_config_path


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
    """Set a configuration value. 
    
    Keys:
    - local-data: Root directory for user data (customers, etc.)
    - cloud-folder-id: Google Drive folder ID for backups
    """
    data = load_main_config()
    
    # Map CLI keys to config keys
    key_map = {
        'local-data': 'local_data',
        'cloud-folder-id': 'google_drive_all_customers_folder_id',
        # Legacy support
        'customers-local-path': 'local_data'
    }
    
    real_key = key_map.get(key)
    if not real_key:
        click.echo(f"Unknown config key: {key}. Valid keys: {', '.join(key_map.keys())}", err=True)
        sys.exit(1)
        
    data[real_key] = value
    path = save_main_config(data)
    click.echo(f"Updated {key} in {path}")
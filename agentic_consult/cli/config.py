import click
import sys
import yaml

from agentic_consult.customers import get_active_customers_root
from agentic_consult.config import load_main_config, save_main_config


@click.group()
def config():
    """Manage global configuration."""
    pass

@config.command(name='show')
def config_show():
    """Show current configuration."""
    data = load_main_config()
    
    # Show resolved paths first
    root = get_active_customers_root()
    click.echo(f"# Active Customers Root: {root}")

    # Count customers
    customer_count = 0
    if root.exists():
        for d in root.iterdir():
            if d.is_dir() and (d / 'customer.yaml').exists():
                customer_count += 1
    click.echo(f"# Found {customer_count} customer(s).")

    if not data:
        click.echo("# No global config.yaml found (using defaults).")
    else:
        click.echo(yaml.dump(data))

@config.command(name='set')
@click.argument('key')
@click.argument('value')
def config_set(key, value):
    """Set a configuration value. 
    
    Keys:
    - customers-local-path: Path to local customers directory
    - customers-cloud-folder-id: Google Drive folder ID for backups
    """
    data = load_main_config()
    
    # Map CLI keys to config keys
    key_map = {
        'customers-local-path': 'customers_local_path',
        'customers-cloud-folder-id': 'google_drive_all_customers_folder_id'
    }
    
    real_key = key_map.get(key)
    if not real_key:
        click.echo(f"Unknown config key: {key}. Valid keys: {', '.join(key_map.keys())}", err=True)
        sys.exit(1)
        
    data[real_key] = value
    path = save_main_config(data)
    click.echo(f"Updated {key} in {path}")

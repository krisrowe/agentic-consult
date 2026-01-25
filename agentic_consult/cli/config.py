import click
import sys
import json
import yaml
import os

from agentic_consult.customers import get_active_customers_root
from agentic_consult.config import load_main_config, save_main_config, get_config_path
from .user_home import user_home_cli, get_default_user_home_config
from agentic_consult.sdk.hooks import get_hook_status, install_hook


@click.group()
def config():
    """Manage global configuration."""
    pass

@config.command(name='init')
def config_init():
    """Initialize configuration with default settings (Idempotent)."""
    current_data = load_main_config()
    path = get_config_path()
    
    defaults = {
        "backups": {
            "user_home": get_default_user_home_config()
        }
    }
    
    changes = []
    
    def deep_merge(target, source, prefix=""):
        for key, value in source.items():
            full_key = f"{prefix}.{key}" if prefix else key
            
            if key not in target:
                target[key] = value
                changes.append(f"Added setting '{full_key}' with value: {value}")
            elif isinstance(value, dict) and isinstance(target[key], dict):
                deep_merge(target[key], value, full_key)
            elif key == "paths" and isinstance(value, list) and isinstance(target[key], list):
                # Special handling for paths list: Append missing items
                for item in value:
                    if item not in target[key]:
                        target[key].append(item)
                        changes.append(f"Added item '{item}' to list '{full_key}'")
    
    deep_merge(current_data, defaults)
    
    if not path.exists():
        changes.insert(0, f"Created new settings file at {path}")
        save_main_config(current_data)
        click.echo(f"Initialized configuration at {path}")
    elif changes:
        save_main_config(current_data)
        click.echo(f"Updated configuration at {path}")
    else:
        click.echo(f"Configuration at {path} is already up to date.")
        
    for change in changes:
        click.echo(f"- {change}")

    # Initialize app.yaml (User Override)
    from agentic_consult.config import initialize_app_config
    
    success, msg = initialize_app_config()
    click.echo(msg)

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

    # Build output object with settings and precommit status
    hook_status = get_hook_status()
    output = {
        "settings": data if data else {},
        "precommit": {
            "hooks": {
                "installed": hook_status["installed"],
                "location": hook_status["location"]
            }
        }
    }
    click.echo(json.dumps(output, indent=2))

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


# Precommit subgroup
@config.group(name='precommit')
def config_precommit():
    """Manage pre-commit hook configuration."""
    pass


@config_precommit.command(name='show')
def precommit_show():
    """Show pre-commit hook status."""
    status = get_hook_status()
    output = {
        "hooks": {
            "installed": status["installed"],
            "location": status["location"]
        }
    }
    click.echo(json.dumps(output, indent=2))


@config_precommit.command(name='install')
def precommit_install():
    """Install the consult pre-commit hook globally.

    Installs to ~/.config/git/hooks/ and configures git core.hooksPath.
    Idempotent - safe to run multiple times.
    """
    result = install_hook()

    if result["success"]:
        click.secho(f"✅ {result['message']}", fg="green")
        if result["path"]:
            click.echo(f"   Location: {result['path']}")
    else:
        click.secho(f"❌ {result['message']}", fg="red")
        if result["path"]:
            click.echo(f"   Location: {result['path']}")
        sys.exit(1)

import click
import sys
import json
import yaml
import os
from pathlib import Path
from rich.console import Console
from rich.table import Table

from agentic_consult.customers import get_active_customers_root
from agentic_consult.config import (
    load_main_config, 
    save_main_config, 
    get_config_path, 
    load_app_config,
    deep_merge
)
from agentic_consult.schema import validate_yaml
from .user_home import user_home_cli, get_default_user_home_config

console = Console()

@click.group()
def config():
    """Manage global configuration."""
    pass

@config.command(name='list')
def config_list():
    """List all available configuration settings and their current values."""
    # Load merged config (Package Defaults + User Overrides)
    app_config = load_app_config()
    
    # Load schema for descriptions
    import agentic_consult.config as config_pkg
    schema_path = Path(config_pkg.__file__).parent / "schemas" / "app_schema.json"
    schema = {}
    if schema_path.exists():
        with open(schema_path, 'r') as f:
            schema = json.load(f)
            
    # Flatten config and schema properties
    def get_description(key_path, schema_root):
        """Walks schema to find description for a dotted key."""
        parts = key_path.split('.')
        current = schema_root.get("properties", {})
        for i, part in enumerate(parts):
            if part not in current:
                return ""
            
            props = current[part]
            if i == len(parts) - 1:
                return props.get("description", "")
            
            if props.get("type") == "object":
                current = props.get("properties", {})
            else:
                return "" # Can't drill further
        return ""

    def flatten(d, parent_key='', sep='.'):
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(flatten(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)

    flat_config = flatten(app_config)
    
    table = Table(title="Agentic Consult Configuration (app.yaml)")
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Value", style="green")
    table.add_column("Description", style="dim")
    
    for key, value in sorted(flat_config.items()):
        # Redact sensitive keys
        if "api_key" in key or "token" in key:
            value = "********"
        
        desc = get_description(key, schema)
        table.add_row(key, str(value), desc)
        
    console.print(table)
    console.print(f"\n[dim]User overrides loaded from: {get_config_path('app.yaml')}[/dim]")

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

    if not data:
        click.echo("# No global settings.json found (using defaults).")
    else:
        click.echo(json.dumps(data, indent=2))

def is_key_in_schema(key_path: str) -> bool:
    """Checks if a dot-notation key exists in the app_schema.json."""
    import agentic_consult.config as config_pkg
    
    schema_path = Path(config_pkg.__file__).parent / "schemas" / "app_schema.json"
    if not schema_path.exists():
        return False
        
    try:
        with open(schema_path, 'r') as f:
            schema = json.load(f)
            
        current = schema.get("properties", {})
        parts = key_path.split('.')
        
        for i, part in enumerate(parts):
            if part not in current:
                return False
            
            # If we are at the last part, we found it
            if i == len(parts) - 1:
                return True
                
            # Drill down
            props = current[part]
            if props.get("type") == "object":
                current = props.get("properties", {})
            elif props.get("type") == "array":
                # Arrays are leaf nodes for setting, we don't drill into items
                return True
            else:
                # Scalar encountered before end of path
                return False
        return True
    except Exception:
        return False

def set_nested_value(data: dict, key_path: str, value: any):
    """Sets a value in a nested dictionary using dot notation."""
    keys = key_path.split('.')
    current = data
    for k in keys[:-1]:
        if k not in current or not isinstance(current[k], dict):
            current[k] = {}
        current = current[k]
    current[keys[-1]] = value

def delete_nested_key(data: dict, key_path: str):
    """Deletes a key in a nested dictionary using dot notation. Prunes empty parents."""
    keys = key_path.split('.')
    if len(keys) == 1:
        if keys[0] in data:
            del data[keys[0]]
        return

    # Navigate to parent
    parent = data
    stack = [parent]
    for k in keys[:-1]:
        if k not in parent or not isinstance(parent[k], dict):
            return # Key path doesn't exist
        parent = parent[k]
        stack.append(parent)
    
    # Delete leaf
    if keys[-1] in parent:
        del parent[keys[-1]]
    
    # Prune empty parents up the stack
    for i in range(len(keys) - 1, 0, -1):
        child_key = keys[i-1]
        parent_node = stack[i-1]
        child_node = stack[i]
        if not child_node: # If dict is empty
            if child_key in parent_node:
                del parent_node[child_key]

@config.command(name='set')
@click.argument('key')
@click.argument('value')
def config_set(key, value):
    """Set a configuration value. Supports dot-notation.
    
    Smart Routing:
    - If key matches app_schema.json (e.g. gemini.api_key), updates user's app.yaml (Validated).
    - Otherwise, updates settings.json (Legacy).
    """
    # Handle boolean/int conversion
    if value.lower() == 'true':
        real_value = True
    elif value.lower() == 'false':
        real_value = False
    elif value.isdigit():
        real_value = int(value)
    else:
        real_value = value

    if is_key_in_schema(key):
        # Target: app.yaml
        target_file = get_config_path("app.yaml")
        
        # 1. Load User Config (or create empty)
        if target_file.exists():
            with open(target_file, 'r', encoding='utf-8') as f:
                user_config = yaml.safe_load(f) or {}
        else:
            user_config = {}
            
        # 2. Apply change to copy of FULL config for validation
        full_config = load_app_config() # Current valid state
        # Create a deep copy or re-merge to simulate the new state
        # Simpler: just set it in user config, merge, then validate
        
        # We need to simulate the merge
        test_user_config = json.loads(json.dumps(user_config)) # Deep copy
        set_nested_value(test_user_config, key, real_value)
        
        # Merge test user config onto default config (re-load default)
        import agentic_consult.config as config_pkg
        pkg_app_yaml = Path(config_pkg.__file__).parent / "app.yaml"
        with open(pkg_app_yaml, 'r', encoding='utf-8') as f:
            test_full_config = yaml.safe_load(f) or {}
        
        deep_merge(test_full_config, test_user_config)
        
        try:
            validate_yaml(test_full_config, "app_schema.json")
        except Exception as e:
            click.secho(f"❌ Validation Failed: {e}", fg="red")
            sys.exit(1)
            
        # 3. If valid, apply to user config and save
        set_nested_value(user_config, key, real_value)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        with open(target_file, 'w', encoding='utf-8') as f:
            yaml.dump(user_config, f)
            
        click.echo(f"Updated {key} in {target_file}")
        
    else:
        # Target: settings.json (Legacy)
        data = load_main_config()
        
        # Map legacy CLI keys
        key_map = {
            'local-data': 'local_data',
            'cloud-folder-id': 'google_drive_all_customers_folder_id',
            'customers-local-path': 'local_data'
        }
        real_key = key_map.get(key, key)
        
        set_nested_value(data, real_key, real_value)
        
        path = save_main_config(data)
        click.echo(f"Updated {real_key} in {path}")

@config.command(name='unset')
@click.argument('key')
def config_unset(key):
    """Remove a user override for a configuration key."""
    if is_key_in_schema(key):
        target_file = get_config_path("app.yaml")
        if not target_file.exists():
            click.echo("No user configuration found to unset.")
            return
            
        with open(target_file, 'r', encoding='utf-8') as f:
            user_config = yaml.safe_load(f) or {}
            
        delete_nested_key(user_config, key)
        
        with open(target_file, 'w', encoding='utf-8') as f:
            yaml.dump(user_config, f)
            
        click.echo(f"Unset {key} in {target_file}")
    else:
        # Legacy settings.json unset logic could go here if needed
        click.echo("Unsetting legacy keys is not yet supported via CLI. Edit settings.json manually.")
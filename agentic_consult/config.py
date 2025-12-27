import os
import json
import yaml
import click
from pathlib import Path
from agentic_consult.schema import validate_yaml

SETTINGS_FILENAME = "settings.json"

def get_config_path(filename=None):
    """
    Returns the authoritative path for the global settings file or a specific file.
    Always uses the XDG App Config Directory.
    """
    base_dir = Path(click.get_app_dir('agentic-consult'))
    if filename:
        return base_dir / filename
    return base_dir / SETTINGS_FILENAME

def load_main_config():
    """Loads settings from settings.json."""
    path = get_config_path()
    if not path.exists():
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f) or {}
    except (json.JSONDecodeError, IOError):
        return {}

def save_main_config(data):
    """Saves settings to settings.json."""
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    return path

def get_local_data_root():
    """
    Resolves the root directory for all user data.
    Priority:
    1. local_data setting in settings.json
    2. ~/.local/share/agentic-consult/ (Standard XDG Data)
    """
    config = load_main_config()
    if config.get('local_data'):
        return Path(config['local_data'])
    
    # Default XDG Data location
    return Path.home() / ".local" / "share" / "agentic-consult"

def load_yaml_file(path):
    """Helper to load generic YAML files."""
    if not path or not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}
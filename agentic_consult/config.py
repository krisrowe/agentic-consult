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
    Priority:
    1. CONSULT_CONFIG_DIR environment variable
    2. XDG App Config Directory (via click.get_app_dir)
    """
    env_config_dir = os.environ.get('CONSULT_CONFIG_DIR')
    if env_config_dir:
        base_dir = Path(env_config_dir)
    else:
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

def get_backups_google_drive_folder_id() -> str:
    """
    Returns the Google Drive folder ID for backups.
    Checks environment variable 'BACKUPS_GOOGLE_DRIVE_FOLDER_ID' first,
    then the 'backups_google_drive_folder_id' in settings.json.
    """
    env_id = os.environ.get('BACKUPS_GOOGLE_DRIVE_FOLDER_ID')
    if env_id:
        return env_id
    
    config = load_main_config()
    backups_config = config.get('backups', {})
    if isinstance(backups_config, dict):
        return backups_config.get('google_drive_folder_id')
    return None

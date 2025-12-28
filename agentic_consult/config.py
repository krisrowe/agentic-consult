import os
import json
import yaml
import click
from pathlib import Path
from agentic_consult.schema import validate_yaml

SETTINGS_FILENAME = "settings.json"

def get_consult_config_dir() -> Path:
    """
    Returns the base directory for agentic-consult's own settings.
    Priority:
    1. CONSULT_CONFIG_DIR environment variable
    2. XDG App Config Directory (via click.get_app_dir)
    """
    env_config_dir = os.environ.get('CONSULT_CONFIG_DIR')
    if env_config_dir:
        return Path(env_config_dir)
    return Path(click.get_app_dir('agentic-consult'))

def get_config_path(filename=None):
    """
    Returns the authoritative path for the global settings file or a specific file.
    Always uses the result from get_consult_config_dir.
    """
    base_dir = get_consult_config_dir()
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
    """
    Saves settings to settings.json.
    Creates parent directories if they don't exist.
    """
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
    
    # Default XDG Data location (relative to actual HOME, not BACKUPS_HOME_LOCAL_PATH)
    return Path.home() / ".local" / "share" / "agentic-consult"

def load_yaml_file(path):
    """
    Helper to load generic YAML files.
    Returns an empty dict if file not found or invalid.
    """
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except (yaml.YAMLError, IOError):
        return {}

def get_backups_google_drive_folder_id() -> str:
    """
    Returns the Google Drive folder ID for backups.
    Checks environment variable 'BACKUPS_GOOGLE_DRIVE_FOLDER_ID' first,
    then the 'backups.google_drive_folder_id' in settings.json.
    """
    env_id = os.environ.get('BACKUPS_GOOGLE_DRIVE_FOLDER_ID')
    if env_id:
        return env_id
    
    config = load_main_config()
    backups_config = config.get('backups', {})
    if isinstance(backups_config, dict):
        return backups_config.get('google_drive_folder_id')
    return None

def load_app_config(base_dir=None) -> dict:
    """
    Loads configuration from project settings in the specified directory.
    Defaults to current working directory if base_dir is None.
    """
    base = Path(base_dir) if base_dir else Path.cwd()
    app_yaml_path = base / "app.yaml"
    
    if app_yaml_path.exists():
        try:
            with open(app_yaml_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}
    return {}

def resolve_model_alias(model_name: str) -> str:
    """
    Resolves a model alias (e.g., 'fast', 'latest-pro') to a specific model ID.
    If no alias matches, returns the input string.
    """
    if not model_name:
        return model_name
        
    app_config = load_app_config()
    aliases = app_config.get('gemini', {}).get('models', {}).get('aliases', {})
    
    return aliases.get(model_name, model_name)

def get_default_model() -> str:
    """
    Resolves the default Gemini model.
    Strictly requires a default model to be set.
    """
    app_config = load_app_config()
    model = app_config.get('gemini', {}).get('models', {}).get('default')
    
    if not model:
        raise ValueError("A default Gemini model must be defined in the system.")
        
    return resolve_model_alias(model)

def get_model_info() -> dict:
    """
    Returns structured information about available models and aliases.
    """
    app_config = load_app_config()
    models_cfg = app_config.get('gemini', {}).get('models', {})
    return {
        "default": models_cfg.get('default'),
        "available": models_cfg.get('available', []),
        "aliases": models_cfg.get('aliases', {})
    }

def get_model_help_text() -> str:
    """
    Generates a user-facing summary of available models and aliases.
    """
    info = get_model_info()
    aliases = info['aliases']
    
    parts = []
    if aliases:
        alias_str = ", ".join(sorted(aliases.keys()))
        parts.append(f"Supported aliases: {alias_str}")
    
    default = info['default']
    if default:
        parts.append(f"Default: {default}")
        
    return ". ".join(parts) + "." if parts else "No specific models configured."

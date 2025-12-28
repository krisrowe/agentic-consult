import os
import json
import yaml
import re
import click
import logging
from pathlib import Path
from agentic_consult.schema import validate_yaml

logger = logging.getLogger(__name__)

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
    """
    Loads settings from settings.json.
    """
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

def _parse_model_version(model_id: str) -> tuple:
    """
    Parses model ID to sortable tuple: (is_stable, version_float).
    Prioritizes Stability FIRST, then Version.
    Example: 'gemini-2.5-pro' -> (True, 2.5)
             'gemini-3.0-pro-preview' -> (False, 3.0)
    Result: (True, 2.5) > (False, 3.0)
    """
    # Extract version numbers (e.g., 1.5, 2.0)
    match = re.search(r'(\d+(?:\.\d+)?)', model_id)
    version = float(match.group(1)) if match else 0.0
    
    is_stable = not any(x in model_id.lower() for x in ['preview', 'exp', 'experimental'])
    
    return (is_stable, version)

def resolve_model_alias(model_name: str) -> str:
    """
    Resolves abstract aliases ('fast', 'thinking') to the best available model ID based on config.
    Logic:
    - 'fast' -> finds best 'flash' model.
    - 'thinking'/'pro' -> finds best 'pro' model.
    - Ranking: Higher version > Stable > Preview.
    """
    if not model_name:
        return model_name
    
    target = None
    if model_name.lower() in ['fast', 'flash']:
        target = 'flash'
    elif model_name.lower() in ['thinking', 'pro', 'slow']:
        target = 'pro'
    
    if not target:
        # Not a known abstract alias, treat as explicit ID
        return model_name

    app_config = load_app_config()
    available = app_config.get('gemini', {}).get('models', {}).get('available', [])
    
    candidates = [m for m in available if target in m.lower()]
    
    if not candidates:
        return model_name # Fallback to input if no candidates found
        
    # Sort by (Version ASC, Stable ASC), then pick last (highest)
    # Stable=True (1) > Stable=False (0)
    best_match = sorted(candidates, key=_parse_model_version)[-1]
    return best_match

def get_default_model() -> str:
    """
    Resolves the default Gemini model.
    Priority:
    1. User settings (settings.json) - if valid in project config.
    2. Project settings (app.yaml).
    """
    app_config = load_app_config()
    app_default = app_config.get('gemini', {}).get('models', {}).get('default')
    available = app_config.get('gemini', {}).get('models', {}).get('available', [])
    
    # Check User Settings
    user_config = load_main_config()
    user_default = user_config.get('models', {}).get('default')
    
    if user_default:
        # JIT Validation: Must be in available list
        # We need to resolve alias first, in case user set default to "fast"
        resolved_user_default = resolve_model_alias(user_default)
        
        if resolved_user_default in available:
            return resolved_user_default
        else:
            logger.warning(f"User default model '{user_default}' (resolved: {resolved_user_default}) is not in the available list. Falling back to system default.")
    
    if not app_default:
        raise ValueError("A default Gemini model must be defined in the system.")
        
    return resolve_model_alias(app_default)

def get_model_info() -> dict:
    """
    Returns structured information about available models and aliases.
    Calculates the 'effective_default' by resolving user/system settings.
    """
    app_config = load_app_config()
    models_cfg = app_config.get('gemini', {}).get('models', {})
    
    try:
        effective_default = get_default_model()
    except ValueError:
        effective_default = None
        
    return {
        "default": effective_default,
        "system_default": models_cfg.get('default'),
        "available": models_cfg.get('available', []),
        "aliases": models_cfg.get('aliases', {})
    }

def get_model_configuration() -> dict:
    """
    Returns the fully resolved model configuration.
    Includes default, available list, and resolved aliases.
    """
    info = get_model_info()
    
    # Calculate resolutions for standard aliases
    # We check the ones defined in aliases map (if any were there) plus our standard dynamic ones
    standard_aliases = ['fast', 'thinking']
    resolutions = {}
    
    for alias in standard_aliases:
        resolutions[alias] = resolve_model_alias(alias)
        
    return {
        "default": info['default'],
        "available": info['available'],
        "resolutions": resolutions
    }

def get_model_help_text() -> str:
    """
    Generates a user-facing summary of available models and dynamic aliases.
    Structure: Available models -> Dynamic Aliases -> Default.
    """
    info = get_model_info()
    parts = []
    
    # 1. Available Models
    available = info.get('available', [])
    if available:
        parts.append(f"Available models: {', '.join(available)}")
    
    # 2. Dynamic Aliases
    # Calculate what 'fast' and 'thinking' resolve to currently
    aliases_shown = []
    for alias in ['fast', 'thinking']:
        resolved = resolve_model_alias(alias)
        # Only show if it resolves to something different than itself (meaning it found a match)
        if resolved != alias:
            aliases_shown.append(f"{alias} -> {resolved}")
            
    if aliases_shown:
        parts.append(f"Aliases: {', '.join(aliases_shown)}")
    
    # 3. Default
    default = info.get('default')
    if default:
        parts.append(f"Default: {default}")
        
    return ". ".join(parts) + "." if parts else "No specific models configured."

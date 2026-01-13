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
APP_SLUG = "agentic-consult"

def get_default_settings_dir() -> Path:
    """Returns the standard XDG configuration directory for the app."""
    return Path(click.get_app_dir(APP_SLUG))

def get_settings_dir() -> Path:
    """
    Returns directory where settings.json lives.
    Always XDG, unless CONSULT_CONFIG_DIR env var is set (for testing).
    """
    env_config_dir = os.environ.get('CONSULT_CONFIG_DIR')
    if env_config_dir:
        return Path(env_config_dir)
    return get_default_settings_dir()


def _load_settings_json() -> dict:
    """Load settings.json from the settings directory."""
    settings_path = get_settings_dir() / SETTINGS_FILENAME
    if not settings_path.exists():
        return {}
    try:
        with open(settings_path, 'r', encoding='utf-8') as f:
            return json.load(f) or {}
    except (json.JSONDecodeError, IOError):
        return {}


def get_consult_config_dir() -> Path:
    """
    Returns directory for config files (email.yaml, templates/, etc).
    Priority:
    1. CONSULT_CONFIG_DIR env var (for testing)
    2. config_dir in settings.json
    3. Same directory as settings.json
    """
    env_config_dir = os.environ.get('CONSULT_CONFIG_DIR')
    if env_config_dir:
        return Path(env_config_dir)

    settings = _load_settings_json()
    if settings.get('config_dir'):
        return Path(settings['config_dir']).expanduser()

    return get_settings_dir()


def get_config_path(filename=None):
    """
    Returns path to a config file.
    - No filename: returns settings.json path (always in settings dir)
    - With filename: returns path in config dir (may differ from settings dir)
    """
    if filename:
        return get_consult_config_dir() / filename
    return get_settings_dir() / SETTINGS_FILENAME

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

def set_app_config_value(key: str, value: any):
    """
    Updates a single value in settings.json.
    """
    data = load_main_config()
    data[key] = value
    save_main_config(data)

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
        return Path(config['local_data']).expanduser()
    
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

def load_app_config() -> dict:
    """
    Loads core system configuration.
    Priority:
    1. User override in config directory (app.yaml).
    2. Default from package root.
    """
    # 1. Check User Config Directory
    user_path = get_config_path("app.yaml")
    if user_path.exists():
        with open(user_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
            validate_yaml(data, "app_schema.json")
            return data

    # 2. Fallback to Package Default
    path = Path(__file__).parent / "app.yaml"
    
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
            validate_yaml(data, "app_schema.json")
            return data
                
    return {}

def parse_model_version(model_id: str) -> tuple:
    """
    Parses model ID to sortable tuple: (is_stable, version_float, is_standard).
    Prioritizes Stability > Version > Standard Tier (vs Lite).
    Example: 'gemini-2.5-flash'      -> (True, 2.5, True)
             'gemini-2.5-flash-lite' -> (True, 2.5, False)
    Result: (True, 2.5, True) > (True, 2.5, False)
    """
    # Extract version numbers (e.g., 1.5, 2.0)
    match = re.search(r'(\d+(?:\.\d+)?)', model_id)
    version = float(match.group(1)) if match else 0.0
    
    model_lower = model_id.lower()
    is_stable = not any(x in model_lower for x in ['preview', 'exp', 'experimental'])
    is_standard = 'lite' not in model_lower
    
    return (is_stable, version, is_standard)

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
    best_match = sorted(candidates, key=parse_model_version)[-1]
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
        resolved_user_default = resolve_model_alias(user_default)
        if resolved_user_default in available:
            return resolved_user_default
        else:
            logger.warning(f"User default model '{user_default}' (resolved: {resolved_user_default}) is not in the available list. Falling back to system default.")
    
    if not app_default:
        raise ValueError("A default Gemini model must be defined in the system.")
        
    return resolve_model_alias(app_default)

def get_model_configuration() -> dict:
    """
    Returns the fully resolved model configuration.
    Single source of truth for CLI display and help text.
    """
    app_config = load_app_config()
    models_cfg = app_config.get('gemini', {}).get('models', {})
    available = models_cfg.get('available', [])
    system_default = models_cfg.get('default')
    
    # Check user override
    user_config = load_main_config()
    user_default = user_config.get('models', {}).get('default')
    
    try:
        effective_default = get_default_model()
    except ValueError:
        effective_default = None
    
    # Calculate resolutions for standard aliases
    standard_aliases = ['fast', 'thinking']
    resolutions = {}
    
    for alias in standard_aliases:
        resolutions[alias] = resolve_model_alias(alias)
        
    return {
        "default": effective_default,
        "system_default": system_default,
        "user_default": user_default,
        "available": available,
        "resolutions": resolutions
    }

def get_model_help_text() -> str:
    """
    Generates a user-facing summary of available models and dynamic aliases.
    Structure: Available models -> Dynamic Aliases -> Default -> Tip.
    """
    config = get_model_configuration()
    parts = []
    
    # 1. Available Models
    available = config.get('available', [])
    if available:
        parts.append(f"Available models: {', '.join(available)}")
    
    # 2. Dynamic Aliases
    resolutions = config.get('resolutions', {})
    if resolutions:
        alias_list = []
        for alias, target in sorted(resolutions.items()):
            # Since our logic prioritizes stable versions, label them as such for clarity
            alias_list.append(f"{alias} -> {target} (Latest Stable)")
        parts.append(f"Aliases: {', '.join(alias_list)}")
    
    # 3. Default
    default = config.get('default')
    user_override = config.get('user_default')
    if default:
        msg = f"Default: {default}"
        if user_override:
            msg += f" (User Override: '{user_override}')"
        parts.append(msg)
        
    # 4. Tip
    parts.append("Tip: Use 'consult models set-default' to change the default.")
        
    return " ".join(parts)

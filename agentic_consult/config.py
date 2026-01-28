import os
import json
import yaml
import re
import click
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from agentic_consult.schema import validate_yaml
from agentic_consult.paths import (
    get_settings_dir,
    get_settings_path,
    load_settings as _load_settings_json,
    SETTINGS_FILENAME,
    APP_SLUG,
)

logger = logging.getLogger(__name__)


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

def initialize_app_config() -> tuple[bool, str]:
    """
    Initializes the user's app.yaml by copying the default from the package.
    Returns (success, message).
    """
    import shutil
    import agentic_consult.config as config_pkg
    
    user_app_yaml = get_config_path("app.yaml")
    pkg_app_yaml = Path(config_pkg.__file__).parent / "app.yaml"

    if user_app_yaml.exists():
        return False, f"app.yaml already exists at {user_app_yaml}"

    if not pkg_app_yaml.exists():
        return False, "Default package app.yaml not found."

    try:
        # Ensure parent directory exists (e.g. tool-config/)
        user_app_yaml.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pkg_app_yaml, user_app_yaml)
        return True, f"Initialized default app.yaml at {user_app_yaml}"
    except Exception as e:
        return False, f"Failed to copy default app.yaml: {e}"

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

def get_mcp_registration_info(include_token: bool = False) -> dict:
    """
    Returns MCP registration info for manual configuration.

    Args:
        include_token: If True, include full token. If False, mask it.

    Returns:
        Dict with 'url', 'header_auth', 'query_auth', or 'error' if not configured.
    """
    config = load_main_config()
    url = config.get("mcp_url")
    pat = config.get("personal_access_token")

    if not url or not pat:
        return {"error": "Cloud MCP not configured. Run 'consult mcp import' first."}

    token_display = pat if include_token else "************"

    result = {
        "url": url,
        "header_auth": {
            "url": url,
            "header": f"Authorization: Bearer {token_display}",
            "guidance": [
                {"code": "header_support", "message": "For clients that support custom headers."},
            ],
        },
        "query_auth": {
            "url": f"{url.rstrip('/')}?token={token_display}",
            "guidance": [
                {"code": "claude_ai", "message": "For claude.ai custom connectors, use this as simple URL."},
                {"code": "simple_url_fallback", "message": "Try same for others that support simple URL or OAuth2 but not custom headers."},
            ],
        },
    }

    if not include_token:
        result["guidance"] = [
            {"code": "token_masked", "message": "Use --include-token to reveal full token."},
        ]

    return result


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


def get_user_timezone() -> str:
    """Get user's configured timezone name.

    Reads timezone from email.yaml settings. Falls back to UTC
    if not configured.

    Returns:
        IANA timezone name (e.g., "America/Chicago", "UTC")
    """
    try:
        email_config_path = get_config_path("email.yaml")
        if email_config_path.exists():
            with open(email_config_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
                tz_name = data.get('settings', {}).get('timezone')
                if tz_name:
                    return tz_name
    except Exception as e:
        logger.debug(f"Failed to load timezone from email.yaml: {e}")

    return "UTC"


def get_user_datetime() -> datetime:
    """Get current datetime in user's configured timezone."""
    from datetime import timezone
    return localize_datetime(datetime.now(timezone.utc))


def localize_datetime(dt: datetime) -> datetime:
    """Convert a datetime object to the user's configured timezone.

    If the input is naive, it is assumed to be UTC.
    """
    from zoneinfo import ZoneInfo
    from datetime import timezone
    
    tz_name = get_user_timezone()
    try:
        target_tz = ZoneInfo(tz_name)
    except Exception:
        target_tz = ZoneInfo("UTC")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
        
    return dt.astimezone(target_tz)


def backup_config_file(file_path: Path) -> Optional[Path]:
    """Create a timestamped backup of a config file.

    Backup filename includes timezone offset for clarity:
    - email.yaml.replaced-2026-01-21-14-30-00-0600 (CST)
    - email.yaml.replaced-2026-01-21-20-30-00Z (UTC)

    Args:
        file_path: Path to the config file to backup.

    Returns:
        Path to backup file, or None if source doesn't exist.

    Note:
        This manual backup logic can be removed once GCS bucket versioning
        is implemented for the config bucket. See GitHub issue #31.
    """
    if not file_path.exists():
        return None

    now = get_user_datetime()

    # Format timezone offset
    offset = now.strftime("%z")  # e.g., "-0600" or "+0000"
    if offset in ("", "+0000", "-0000"):
        tz_suffix = "Z"
    else:
        tz_suffix = offset  # e.g., "-0600"

    timestamp = now.strftime("%Y-%m-%d-%H-%M-%S") + tz_suffix
    backup_path = file_path.with_suffix(f".yaml.replaced-{timestamp}")

    import shutil
    shutil.copy2(file_path, backup_path)

    return backup_path


def load_updateable(default_path: Path) -> str:
    """
    Load an updateable app resource with GCS hot-patch support.

    Loads from the package-bundled default first, then checks if the same
    filename exists in the app subfolder of config dir. If an updated version
    exists and differs, logs WARN and returns it. Otherwise logs DEBUG.

    This enables hot-patching app resources (templates, docstrings) via
    GCS without image rebuilds, while alerting when drift is detected.

    Args:
        default_path: Absolute path to the package-bundled default file.
                      Caller resolves this (e.g., Path(__file__).parent / "template.txt").

    Returns:
        File content as string. Returns updated content if it exists and differs,
        otherwise returns package content.

    Raises:
        FileNotFoundError: If the default_path doesn't exist.

    Logging:
        - WARN: Updated version differs from package (drift detected)
        - DEBUG: Updated version matches package, or no update (normal operation)

    Note:
        No caching - caller caches if needed. This allows templates to be
        hot-reloaded while docstrings can cache at import time.

        Updated resources live in config/app/ subfolder to separate them from
        user configuration (email.yaml, contacts.yaml, etc.).

        Future: TTL per resource could be added to config-resources.json (YAGNI for now).
    """
    if not default_path.exists():
        raise FileNotFoundError(f"Package default not found: {default_path}")

    package_content = default_path.read_text(encoding='utf-8')
    filename = default_path.name

    # Updateable app resources live in config/app/ subfolder
    update_path = get_consult_config_dir() / "app" / filename

    if update_path.exists():
        updated_content = update_path.read_text(encoding='utf-8')
        if updated_content != package_content:
            logger.warning(f"App resource '{filename}': updated version differs from package")
            return updated_content
        else:
            logger.debug(f"App resource '{filename}': updated version matches package")
            return package_content
    else:
        logger.debug(f"App resource '{filename}': using package default")
        return package_content

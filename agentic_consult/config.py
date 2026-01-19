import os
import json
import yaml
import re
import click
import logging
from pathlib import Path
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

def get_local_data_root() -> Path:
    """
    Returns the root directory for local data (config, topics, customers).
    Resolves priorities:
    1. CONSULT_DATA_ROOT environment variable.
    2. local_data setting in settings.json.
    3. ~/.config/agentic-consult (XDG_CONFIG_HOME fallback).
    """
    if os.environ.get("CONSULT_DATA_ROOT"):
        return Path(os.environ["CONSULT_DATA_ROOT"])
    
    settings = load_main_config()
    if settings.get('local_data'):
        return Path(settings['local_data']).expanduser()

    # Default to XDG path
    xdg_config = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return Path(xdg_config) / "agentic-consult"

def configure_workspace_context(repo_path: Path):
    """
    Bootstraps the shared CONSULT-TOOLS.md context into a repository.
    
    1. Copies CONSULT-TOOLS.md from pkg to ~/.config/agentic-consult/context/
    2. Symlinks ./CONSULT-TOOLS.md -> config location
    3. Updates .gemini/settings.json to include CONSULT-TOOLS.md (and GEMINI.md if initializing)
    4. Registers consult-mcp server if missing.
    """
    import importlib.resources
    import json
    import shutil
    import subprocess

    # 1. Installation
    data_root = get_local_data_root()
    context_dir = data_root / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    target_file = context_dir / "CONSULT-TOOLS.md"

    # Find source in package root
    try:
        pkg_root = importlib.resources.files("agentic_consult").parent
        source_path = pkg_root / "CONSULT-TOOLS.md"
        
        if not source_path.exists():
            # Fallback for development/source tree
            source_path = Path(__file__).parent.parent.parent / "CONSULT-TOOLS.md"

        shutil.copy2(source_path, target_file)
    except Exception as e:
        # Warning only, file might not be packaged yet during dev
        print(f"Warning: Could not locate source CONSULT-TOOLS.md: {e}")

    # 2. Symlinking
    repo_symlink = repo_path / "CONSULT-TOOLS.md"
    
    # Path resolution for symlink (home-relative if possible)
    try:
        home = Path.home()
        if target_file.is_relative_to(home):
            link_target = Path("~") / target_file.relative_to(home)
        else:
            link_target = target_file
    except Exception:
        link_target = target_file

    if repo_symlink.is_symlink() or repo_symlink.exists():
        repo_symlink.unlink()
    
    if target_file.exists():
        os.symlink(target_file, repo_symlink)

    # 3. Registration in .gemini/settings.json
    gemini_dir = repo_path / ".gemini"
    gemini_dir.mkdir(exist_ok=True)
    settings_file = gemini_dir / "settings.json"
    
    settings = {}
    if settings_file.exists():
        try:
            with open(settings_file, 'r') as f:
                settings = json.load(f)
        except Exception:
            pass
            
    if "context" not in settings:
        settings["context"] = {}
        
    # Logic: If fileName exists, append ONLY ours. If missing, init with Default + Ours.
    if "fileName" in settings["context"]:
        filenames = settings["context"]["fileName"]
        if "CONSULT-TOOLS.md" not in filenames:
            filenames.append("CONSULT-TOOLS.md")
    else:
        # Initialize
        filenames = ["GEMINI.md", "CONSULT-TOOLS.md"]
        
    settings["context"]["fileName"] = filenames
    
    with open(settings_file, 'w') as f:
        json.dump(settings, f, indent=2)

    # 4. Check & Register MCP Server
    mcp_registered = False
    
    # Check Project Scope
    if "mcpServers" in settings and "consult" in settings["mcpServers"]:
        mcp_registered = True
        
    # Check User Scope (Simple check of file existence)
    user_settings = Path.home() / ".gemini/settings.json"
    if not mcp_registered and user_settings.exists():
        try:
            with open(user_settings, 'r') as f:
                u_data = json.load(f)
                if "mcpServers" in u_data and "consult" in u_data["mcpServers"]:
                    mcp_registered = True
        except Exception:
            pass
            
    if not mcp_registered:
        # Register at Project Scope via CLI
        try:
            # We use 'gemini mcp add' but inside the repo dir so it defaults to project?
            # No, gemini CLI usually requires --scope project explicitly if that's desired behavior.
            # But here we want to ensure it works for THIS repo.
            subprocess.run(
                ["gemini", "mcp", "add", "consult", "consult-mcp", "--scope", "project"],
                cwd=str(repo_path),
                check=True,
                capture_output=True
            )
            mcp_action = "Registered (Project)"
        except Exception as e:
            mcp_action = f"Failed to register: {e}"
    else:
        mcp_action = "Already Registered"
        
    return {
        "installed": str(target_file),
        "symlink": str(repo_symlink),
        "settings_updated": str(settings_file),
        "filenames": filenames,
        "mcp_status": mcp_action
    }

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

def deep_merge(target: dict, source: dict) -> dict:
    """
    Recursively merges source dict into target dict.
    - Dicts are merged recursively.
    - Lists are OVERWRITTEN by source (standard config behavior).
    - Scalars are overwritten.
    """
    for key, value in source.items():
        if isinstance(value, dict) and key in target and isinstance(target[key], dict):
            deep_merge(target[key], value)
        else:
            target[key] = value
    return target

def load_app_config() -> dict:
    """
    Loads core system configuration by merging user overrides onto package defaults.
    1. Load & Validate Package Default app.yaml
    2. Load User app.yaml (from resolved config dir)
    3. Deep Merge User -> Default
    4. Validate Final Config
    """
    import agentic_consult.config as config_pkg
    
    # 1. Load Package Default
    pkg_app_yaml = Path(config_pkg.__file__).parent / "app.yaml"
    config = {}
    
    if pkg_app_yaml.exists():
        with open(pkg_app_yaml, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
            # Validate defaults immediately to ensure package integrity
            validate_yaml(config, "app_schema.json")
            
    # 2. Load User Override
    user_app_yaml = get_config_path("app.yaml")
    if user_app_yaml.exists():
        with open(user_app_yaml, 'r', encoding='utf-8') as f:
            user_config = yaml.safe_load(f) or {}
            # Merge user config ON TOP OF default config
            deep_merge(config, user_config)

    # 4. Validate final merged config (ensures user didn't break requirements)
    validate_yaml(config, "app_schema.json")
    return config

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

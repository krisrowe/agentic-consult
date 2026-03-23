"""Remote server configuration management.

Settings are stored in settings.json under the 'remote' namespace:
    {
        "remote": {
            "url": "https://consult-mcp-xxx.run.app"
        }
    }

Secrets (access_token, api_key) are read from .credentials.json in the
same config directory, falling back to settings.json for backwards
compatibility.
"""

import json
from dataclasses import dataclass
from typing import Optional
from agentic_consult.config import load_main_config, save_main_config, get_consult_config_dir


@dataclass
class RemoteConfig:
    """Remote server configuration."""
    url: Optional[str] = None
    access_token: Optional[str] = None
    api_key: Optional[str] = None

    @property
    def is_configured(self) -> bool:
        """Returns True if url is set. API Key or Token might be optional depending on auth mode."""
        return bool(self.url)

    @property
    def masked_token(self) -> Optional[str]:
        """Returns masked token for display (first 8 chars + ...)."""
        if not self.access_token:
            return None
        return f"{self.access_token[:8]}..."
        
    @property
    def masked_key(self) -> Optional[str]:
        """Returns masked API key."""
        if not self.api_key:
            return None
        return f"{self.api_key[:8]}..."


def _load_credentials() -> dict:
    """Load secrets from .credentials.json in the config directory."""
    creds_path = get_consult_config_dir() / ".credentials.json"
    if not creds_path.exists():
        return {}
    try:
        with open(creds_path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except (json.JSONDecodeError, IOError):
        return {}


def _save_credentials(data: dict) -> None:
    """Save secrets to .credentials.json in the config directory."""
    creds_path = get_consult_config_dir() / ".credentials.json"
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    with open(creds_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_remote_config() -> RemoteConfig:
    """Load remote configuration from settings.json and .credentials.json.

    Non-secret settings (url) come from settings.json.
    Secrets (access_token, api_key) come from .credentials.json,
    falling back to settings.json for backwards compatibility.
    """
    config = load_main_config()
    remote = config.get("remote", {})
    creds = _load_credentials()

    # Migration: check for legacy keys at root level
    url = remote.get("url") or config.get("mcp_url")
    token = (creds.get("access_token")
             or remote.get("access_token")
             or config.get("personal_access_token"))
    key = creds.get("api_key") or remote.get("api_key")

    return RemoteConfig(url=url, access_token=token, api_key=key)


def set_remote_config(url: Optional[str] = None, access_token: Optional[str] = None, api_key: Optional[str] = None) -> None:
    """
    Update remote configuration.

    Non-secret settings (url) go to settings.json.
    Secrets (access_token, api_key) go to .credentials.json.
    Only updates fields that are provided (not None).
    """
    if url is not None:
        config = load_main_config()
        if "remote" not in config:
            config["remote"] = {}
        config["remote"]["url"] = url
        save_main_config(config)

    if access_token is not None or api_key is not None:
        creds = _load_credentials()
        if access_token is not None:
            creds["access_token"] = access_token
        if api_key is not None:
            creds["api_key"] = api_key
        _save_credentials(creds)


def get_remote_url() -> Optional[str]:
    """Get remote server URL."""
    return get_remote_config().url


def set_remote_url(url: str) -> None:
    """Set remote server URL."""
    set_remote_config(url=url)


def get_access_token() -> Optional[str]:
    """Get access token."""
    return get_remote_config().access_token


def set_access_token(token: str) -> None:
    """Set access token."""
    set_remote_config(access_token=token)


def get_registration_info(include_token: bool = False) -> dict:
    """
    Get registration info for display.

    Returns structured dict with:
    - config: URL, token, key
    - commands: claude and gemini mcp add commands
    - manual: auth options

    Args:
        include_token: If True, include full secrets; otherwise mask them

    Returns:
        Dict with all registration info for CLI display
    """
    cfg = get_remote_config()

    if not cfg.is_configured:
        return {
            "configured": False,
            "error": "Not configured. Run 'consult remote auth import' first.",
        }

    token_display = cfg.access_token if include_token else "****"
    token_masked = cfg.masked_token
    key_display = cfg.api_key if include_token else "****"
    key_masked = cfg.masked_key

    # MCP Stateless HTTP endpoint is at root /
    base_url = cfg.url.rstrip('/')
    
    # Construct auth query params
    # We use API Key ONLY.
    query_params = []
    if cfg.api_key:
        query_params.append(f"key={key_display}")
         
    query_str = "&".join(query_params)
    full_url = f"{base_url}/?{query_str}" if query_str else f"{base_url}/"

    return {
        "configured": True,
        "config": {
            "url": cfg.url,
            "key_masked": key_masked,
            "key_full": cfg.api_key if include_token else None,
        },
        "commands": {
            "claude": f'claude mcp add --transport http -s user consult "{full_url}"',
            "gemini": f'gemini mcp add consult "{full_url}" --scope user --transport http',
        },
        "manual": {
            "simple": {
                "url": full_url,
            },
        },
    }


def migrate_legacy_config() -> bool:
    """
    Migrate legacy config keys to new namespace.

    Moves:
        mcp_url -> remote.url
        personal_access_token -> remote.access_token

    Returns True if migration was performed.
    """
    config = load_main_config()
    migrated = False

    # Check for legacy keys
    legacy_url = config.get("mcp_url")
    legacy_token = config.get("personal_access_token")

    if legacy_url or legacy_token:
        # Ensure remote namespace exists
        if "remote" not in config:
            config["remote"] = {}

        # Migrate if not already set in new location
        if legacy_url and not config["remote"].get("url"):
            config["remote"]["url"] = legacy_url
            migrated = True

        if legacy_token and not config["remote"].get("access_token"):
            config["remote"]["access_token"] = legacy_token
            migrated = True

        # Remove legacy keys
        if legacy_url:
            del config["mcp_url"]
            migrated = True
        if legacy_token:
            del config["personal_access_token"]
            migrated = True

        if migrated:
            save_main_config(config)

    return migrated

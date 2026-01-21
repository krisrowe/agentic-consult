"""Remote server configuration management.

Settings are stored in settings.json under the 'remote' namespace:
    {
        "remote": {
            "url": "https://consult-mcp-xxx.run.app",
            "access_token": "abc123..."
        }
    }
"""

from dataclasses import dataclass
from typing import Optional
from agentic_consult.config import load_main_config, save_main_config


@dataclass
class RemoteConfig:
    """Remote server configuration."""
    url: Optional[str] = None
    access_token: Optional[str] = None

    @property
    def is_configured(self) -> bool:
        """Returns True if both url and access_token are set."""
        return bool(self.url and self.access_token)

    @property
    def masked_token(self) -> Optional[str]:
        """Returns masked token for display (first 8 chars + ...)."""
        if not self.access_token:
            return None
        return f"{self.access_token[:8]}..."


def get_remote_config() -> RemoteConfig:
    """Load remote configuration from settings.json."""
    config = load_main_config()
    remote = config.get("remote", {})

    # Migration: check for legacy keys at root level
    url = remote.get("url") or config.get("mcp_url")
    token = remote.get("access_token") or config.get("personal_access_token")

    return RemoteConfig(url=url, access_token=token)


def set_remote_config(url: Optional[str] = None, access_token: Optional[str] = None) -> None:
    """
    Update remote configuration in settings.json.

    Only updates fields that are provided (not None).
    """
    config = load_main_config()

    # Ensure remote namespace exists
    if "remote" not in config:
        config["remote"] = {}

    if url is not None:
        config["remote"]["url"] = url
    if access_token is not None:
        config["remote"]["access_token"] = access_token

    save_main_config(config)


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
    - config: URL and token (masked unless include_token=True)
    - commands: claude and gemini mcp add commands
    - manual: header and query string auth options

    Args:
        include_token: If True, include full token; otherwise mask it

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

    # MCP endpoint URL (base URL + /mcp path)
    mcp_url = f"{cfg.url.rstrip('/')}/mcp"

    return {
        "configured": True,
        "config": {
            "url": cfg.url,
            "token_masked": token_masked,
            "token_full": cfg.access_token if include_token else None,
        },
        "commands": {
            "claude": f'claude mcp add --transport http --header "Authorization: Bearer {token_display}" -s user consult {mcp_url}',
            "gemini": f'gemini mcp add consult "{mcp_url}?token={token_display}" --scope user',
        },
        "manual": {
            "header_auth": {
                "url": mcp_url,
                "header": f"Authorization: Bearer {token_display}",
            },
            "query_auth": {
                "url": f"{mcp_url}?token={token_display}",
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

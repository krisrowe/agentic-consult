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

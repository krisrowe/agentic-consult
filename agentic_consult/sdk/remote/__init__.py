"""SDK for remote MCP server operations.

This module provides functions for:
- Reading/writing remote server configuration (url, access_token)
- Health checks and auth validation
- MCP tool invocation
"""

from .config import (
    get_remote_config,
    set_remote_config,
    get_remote_url,
    set_remote_url,
    get_access_token,
    set_access_token,
    get_registration_info,
    RemoteConfig,
)

from .client import (
    check_health,
    check_auth,
    call_tool,
    get_full_status,
    RemoteStatus,
)

__all__ = [
    # Config
    "get_remote_config",
    "set_remote_config",
    "get_remote_url",
    "set_remote_url",
    "get_access_token",
    "set_access_token",
    "get_registration_info",
    "RemoteConfig",
    # Client
    "check_health",
    "check_auth",
    "call_tool",
    "get_full_status",
    "RemoteStatus",
]

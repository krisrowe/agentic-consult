"""Remote MCP server client operations.

Provides functions for:
- Health checks (unauthenticated)
- Auth validation (authenticated)
- MCP tool invocation
"""

import json
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Optional, Any
from .config import get_remote_config, RemoteConfig


@dataclass
class RemoteStatus:
    """Status of remote server connectivity and auth."""
    config: RemoteConfig
    health_ok: bool = False
    health_error: Optional[str] = None
    auth_ok: bool = False
    auth_error: Optional[str] = None
    tool_result: Optional[dict] = None
    tool_error: Optional[str] = None

    @property
    def is_healthy(self) -> bool:
        """Returns True if health check passed."""
        return self.health_ok

    @property
    def is_authenticated(self) -> bool:
        """Returns True if auth check passed."""
        return self.auth_ok


def check_health(url: str, timeout: int = 10) -> tuple[bool, Optional[str]]:
    """
    Check if remote server is reachable via /health endpoint.

    Args:
        url: Base URL of the MCP server
        timeout: Request timeout in seconds

    Returns:
        (success, error_message) tuple
    """
    health_url = f"{url.rstrip('/')}/health"
    try:
        req = urllib.request.Request(health_url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return True, None
            return False, f"Unexpected status {resp.status}"
    except urllib.error.URLError as e:
        return False, str(e.reason)
    except Exception as e:
        return False, str(e)


def check_auth(url: str, token: str, timeout: int = 10) -> tuple[bool, Optional[str]]:
    """
    Validate auth token against remote server.

    Sends a minimal MCP request to /mcp endpoint to verify token validity.

    Args:
        url: Base URL of the MCP server
        token: Access token
        timeout: Request timeout in seconds

    Returns:
        (success, error_message) tuple
    """
    mcp_url = f"{url.rstrip('/')}/mcp"
    try:
        req = urllib.request.Request(mcp_url, method="POST")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Content-Type", "application/json")
        # Send minimal MCP initialize request
        req.data = b'{"jsonrpc": "2.0", "method": "initialize", "id": 1}'
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # Any 2xx means auth passed
            return True, None
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "No token provided"
        elif e.code == 403:
            return False, "Invalid token"
        elif e.code == 500:
            return False, "Server misconfigured"
        else:
            # Other errors (400, 404, etc.) might mean auth passed but request was bad
            return True, None
    except urllib.error.URLError as e:
        return False, str(e.reason)
    except Exception as e:
        return False, str(e)


def call_tool(
    url: str,
    token: str,
    tool_name: str,
    arguments: Optional[dict] = None,
    timeout: int = 30
) -> tuple[Optional[Any], Optional[str]]:
    """
    Call an MCP tool on the remote server.

    Args:
        url: Base URL of the MCP server
        token: Access token
        tool_name: Name of the tool to call
        arguments: Tool arguments (default: {})
        timeout: Request timeout in seconds

    Returns:
        (result, error_message) tuple
    """
    mcp_url = f"{url.rstrip('/')}/mcp"
    try:
        req = urllib.request.Request(mcp_url, method="POST")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps({
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments or {}},
            "id": 2
        }).encode()

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode())

            if "error" in result:
                return None, str(result["error"])

            if "result" in result:
                content = result["result"]
                # Handle MCP tool response format (list of content blocks)
                if isinstance(content, list) and content:
                    text = content[0].get("text", "{}")
                    if isinstance(text, str):
                        try:
                            return json.loads(text), None
                        except json.JSONDecodeError:
                            return text, None
                    return text, None
                return content, None

            return None, "Unexpected response format"

    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return None, str(e.reason)
    except Exception as e:
        return None, str(e)


def get_full_status(test_tool: Optional[str] = "email_triage_stats") -> RemoteStatus:
    """
    Get comprehensive status of remote server.

    Performs:
    1. Health check (unauthenticated)
    2. Auth validation (authenticated)
    3. Optional tool call (if test_tool specified)

    Args:
        test_tool: Tool to call for functional test (None to skip)

    Returns:
        RemoteStatus with all check results
    """
    config = get_remote_config()
    status = RemoteStatus(config=config)

    if not config.is_configured:
        status.health_error = "Not configured"
        status.auth_error = "Not configured"
        return status

    # Health check
    status.health_ok, status.health_error = check_health(config.url)

    if not status.health_ok:
        return status

    # Auth check
    status.auth_ok, status.auth_error = check_auth(config.url, config.access_token)

    if not status.auth_ok:
        return status

    # Tool test (optional)
    if test_tool:
        result, error = call_tool(config.url, config.access_token, test_tool)
        if error:
            status.tool_error = error
        else:
            status.tool_result = result

    return status

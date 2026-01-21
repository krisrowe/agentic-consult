"""MCP client - JSON-RPC over stdio or HTTP transport.

Provides reusable functions for MCP protocol operations with
pluggable transport (stdio subprocess or HTTP).
"""

import json
import shutil
import subprocess
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

from .remote.config import get_remote_config


# Transport callback type: takes JSON-RPC request(s), returns response(s)
Transport = Callable[[list[dict]], list[dict]]


def _build_init_request(request_id: int = 1) -> dict:
    """Build MCP initialize request."""
    return {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "consult-client", "version": "1.0"}
        },
        "id": request_id
    }


def _build_tool_call(tool_name: str, arguments: dict = None, request_id: int = 2) -> dict:
    """Build MCP tools/call request."""
    return {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments or {}},
        "id": request_id
    }


def _parse_tool_result(response: dict) -> tuple[Optional[dict], Optional[str]]:
    """Parse tool call response, return (result, error)."""
    if "error" in response:
        return None, str(response["error"])

    result = response.get("result", {})

    # Check for structuredContent first (preferred)
    if isinstance(result, dict) and "structuredContent" in result:
        return result["structuredContent"], None

    # Fall back to parsing text from content blocks
    if isinstance(result, dict) and "content" in result:
        content = result["content"]
        if isinstance(content, list) and content:
            text = content[0].get("text", "{}")
            try:
                return json.loads(text), None
            except json.JSONDecodeError:
                return {"raw": text}, None

    return result, None


# --- Transports ---

def stdio_transport(cmd: str = "consult-mcp") -> Transport:
    """
    Create stdio transport using subprocess.

    Args:
        cmd: Command to run (must be on PATH)

    Returns:
        Transport function
    """
    def transport(requests: list[dict]) -> list[dict]:
        cmd_path = shutil.which(cmd)
        if not cmd_path:
            raise RuntimeError(f"{cmd} not found on PATH")

        input_data = "\n".join(json.dumps(r) for r in requests) + "\n"

        proc = subprocess.run(
            [cmd_path],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=30
        )

        responses = []
        for line in proc.stdout.strip().split("\n"):
            if line:
                try:
                    responses.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        if proc.returncode != 0 and not responses:
            raise RuntimeError(f"Process failed: {proc.stderr[:200]}")

        return responses

    return transport


def http_transport(url: str = None, token: str = None) -> Transport:
    """
    Create HTTP transport.

    Args:
        url: MCP server URL (default: from config)
        token: Auth token (default: from config)

    Returns:
        Transport function
    """
    MCP_ACCEPT = "application/json, text/event-stream"

    def _parse_sse(data: bytes) -> Optional[dict]:
        """Parse SSE response to extract JSON from 'data:' lines."""
        text = data.decode("utf-8")
        for line in text.split("\n"):
            if line.startswith("data: "):
                try:
                    return json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
        return None

    def transport(requests: list[dict]) -> list[dict]:
        nonlocal url, token

        if not url or not token:
            cfg = get_remote_config()
            if not cfg.is_configured:
                raise RuntimeError("Remote not configured. Run 'consult remote auth import' first.")
            url = url or cfg.url
            token = token or cfg.access_token

        mcp_url = f"{url.rstrip('/')}/mcp"
        responses = []
        session_id = None

        for req in requests:
            http_req = urllib.request.Request(mcp_url, method="POST")
            http_req.add_header("Authorization", f"Bearer {token}")
            http_req.add_header("Content-Type", "application/json")
            http_req.add_header("Accept", MCP_ACCEPT)
            if session_id:
                http_req.add_header("Mcp-Session-Id", session_id)
            http_req.data = json.dumps(req).encode()

            try:
                with urllib.request.urlopen(http_req, timeout=30) as resp:
                    # Capture session ID from init response
                    if not session_id:
                        session_id = resp.headers.get("Mcp-Session-Id")

                    # Parse SSE response
                    parsed = _parse_sse(resp.read())
                    if parsed:
                        responses.append(parsed)
                    else:
                        responses.append({"error": "Failed to parse SSE response"})

            except urllib.error.HTTPError as e:
                responses.append({"error": {"code": e.code, "message": e.reason}})
            except Exception as e:
                responses.append({"error": str(e)})

        return responses

    return transport


# --- High-level operations ---

def call_tool(
    tool_name: str,
    arguments: dict = None,
    mode: Literal["local", "remote"] = "local"
) -> tuple[Optional[dict], Optional[str]]:
    """
    Call an MCP tool.

    Args:
        tool_name: Name of the tool to call
        arguments: Tool arguments
        mode: "local" for stdio, "remote" for HTTP

    Returns:
        (result, error) tuple
    """
    transport = stdio_transport() if mode == "local" else http_transport()

    requests = [
        _build_init_request(1),
        _build_tool_call(tool_name, arguments, 2)
    ]

    try:
        responses = transport(requests)
    except Exception as e:
        return None, str(e)

    if len(responses) < 2:
        return None, f"Expected 2 responses, got {len(responses)}"

    # Check init succeeded
    init_resp = responses[0]
    if "error" in init_resp:
        return None, f"Init failed: {init_resp['error']}"

    # Parse tool result
    return _parse_tool_result(responses[1])


def get_email_stats(mode: Literal["local", "remote"] = "local") -> dict:
    """
    Get email triage stats from MCP server.

    Args:
        mode: "local" for stdio, "remote" for HTTP

    Returns:
        Stats dict or error dict
    """
    result, error = call_tool("email_triage_stats", {}, mode)
    if error:
        return {"error": error}
    return result

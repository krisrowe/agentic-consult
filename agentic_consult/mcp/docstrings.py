"""
MCP tool docstring loader.

Loads tool docstrings from {tool_name}.md files with GCS hot-patch support.
Docstrings are cached at import time since MCP reads them once at registration.

Usage:
    from agentic_consult.mcp.docstrings import get_tool_docstring

    docstring = get_tool_docstring("triage_emails")

See DESIGN.md section 15 for details on updateable app resources.
"""

import logging
from pathlib import Path
from typing import Optional

from agentic_consult.config import load_updateable

logger = logging.getLogger(__name__)

# Directory containing docstring markdown files
_DOCSTRINGS_DIR = Path(__file__).parent

# Cached docstrings (loaded once at startup)
_cached_docstrings: dict[str, str] = {}


def get_tool_docstring(tool_name: str) -> Optional[str]:
    """
    Get the docstring for a specific MCP tool.

    Loads from {tool_name}.md in the mcp directory.

    Args:
        tool_name: Name of the tool (e.g., "triage_emails")

    Returns:
        Docstring text if found, None otherwise.
    """
    if tool_name in _cached_docstrings:
        return _cached_docstrings[tool_name]

    md_path = _DOCSTRINGS_DIR / f"{tool_name}.md"
    try:
        content = load_updateable(md_path)
        _cached_docstrings[tool_name] = content
        return content
    except FileNotFoundError:
        logger.debug(f"No docstring file for tool: {tool_name}")
        return None


def reload_docstrings() -> None:
    """Force reload of docstrings from disk (useful for testing)."""
    global _cached_docstrings
    _cached_docstrings = {}

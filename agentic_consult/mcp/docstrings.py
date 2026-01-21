"""
MCP tool docstring loader.

Loads tool docstrings from tool-docstrings.json with GCS hot-patch support.
Docstrings are cached at import time since MCP reads them once at registration.

Usage:
    from agentic_consult.mcp.docstrings import get_tool_docstring

    docstring = get_tool_docstring("triage_emails")

See DESIGN.md section 15 for details on updateable app resources.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from agentic_consult.config import load_updateable

logger = logging.getLogger(__name__)

# Package docstrings file path
_PACKAGE_DOCSTRINGS_PATH = Path(__file__).parent / "tool-docstrings.json"

# Cached docstrings (loaded once at startup)
_cached_docstrings: Optional[dict[str, str]] = None


def _load_docstrings() -> dict[str, str]:
    """Load tool docstrings using load_updateable()."""
    try:
        content = load_updateable(_PACKAGE_DOCSTRINGS_PATH)
        return json.loads(content)
    except FileNotFoundError:
        logger.warning("Tool docstrings: package file not found")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Tool docstrings: invalid JSON - {e}")
        return {}


def get_tool_docstring(tool_name: str) -> Optional[str]:
    """
    Get the docstring for a specific MCP tool.

    Args:
        tool_name: Name of the tool (e.g., "triage_emails")

    Returns:
        Docstring text if found, None otherwise.
    """
    global _cached_docstrings

    if _cached_docstrings is None:
        _cached_docstrings = _load_docstrings()

    return _cached_docstrings.get(tool_name)


def reload_docstrings() -> None:
    """Force reload of docstrings from disk (useful for testing)."""
    global _cached_docstrings
    _cached_docstrings = None

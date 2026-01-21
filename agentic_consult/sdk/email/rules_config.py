"""SDK for email rules configuration management.

Pure SDK operations for runtime config management of email.yaml.
Used by both MCP tools and REST/CLI layers.
"""

from pathlib import Path
from typing import Optional

import yaml

from agentic_consult.config import get_config_path, backup_config_file
from agentic_consult.mcp.email_schema import validate_email_config, EmailConfig

EMAIL_CONFIG_FILE = "email.yaml"


def get_email_config_path() -> Path:
    """Returns path to email.yaml config file."""
    return get_config_path(EMAIL_CONFIG_FILE)


def load_email_config() -> dict:
    """Load email.yaml configuration.

    Returns:
        Config dict. Empty structure if file doesn't exist.
    """
    path = get_email_config_path()
    if not path.exists():
        return {"settings": None, "rules": [], "enable": [], "disable": []}

    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def save_email_config(
    data: dict,
    backup: bool = True,
    validate: bool = True
) -> tuple[Path, Optional[Path], bool]:
    """Save email.yaml configuration with optional backup and validation.

    Args:
        data: Config dict to save.
        backup: If True, backup existing file before overwriting.
        validate: If True, validate against Pydantic schema.

    Returns:
        Tuple of (config_path, backup_path or None, changed: bool).

    Raises:
        pydantic.ValidationError: If validation fails.
    """
    if validate:
        validate_email_config(data)

    path = get_email_config_path()
    backup_path = None

    # Check if content unchanged
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            existing = yaml.safe_load(f) or {}
        if existing == data:
            return path, None, False  # No change needed

        if backup:
            backup_path = backup_config_file(path)

    # Write new content
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

    return path, backup_path, True


def import_email_config(data: dict) -> dict:
    """Import (replace) email.yaml configuration.

    Validates, backs up existing, and writes new config.

    Args:
        data: Full config dict to import.

    Returns:
        Result dict with status, path, backup_path.

    Raises:
        pydantic.ValidationError: If validation fails.
    """
    path, backup_path, changed = save_email_config(data, backup=True, validate=True)

    if not changed:
        return {"status": "unchanged", "path": str(path)}

    return {
        "status": "updated",
        "path": str(path),
        "backup_path": str(backup_path) if backup_path else None
    }


def export_email_config() -> dict:
    """Export current email.yaml configuration.

    Returns:
        Config dict (empty structure if file doesn't exist).
    """
    return load_email_config()

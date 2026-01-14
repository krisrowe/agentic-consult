"""Path resolution for agentic-consult.

This module can be:
1. Imported by other Python code: from agentic_consult.paths import get_settings_dir
2. Run directly as a script: python3 agentic_consult/paths.py

The __main__ block outputs JSON for terraform's external data source.
Zero external dependencies - stdlib only.
"""
import os
import json
import pathlib

SETTINGS_FILENAME = "settings.json"
APP_SLUG = "agentic-consult"


def get_settings_dir() -> pathlib.Path:
    """Returns settings directory. Respects CONSULT_CONFIG_DIR env var."""
    if env_dir := os.environ.get("CONSULT_CONFIG_DIR"):
        return pathlib.Path(env_dir)
    # XDG default
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return pathlib.Path(xdg_config) / APP_SLUG
    return pathlib.Path.home() / ".config" / APP_SLUG


def get_settings_path() -> pathlib.Path:
    """Returns path to settings.json."""
    return get_settings_dir() / SETTINGS_FILENAME


def load_settings() -> dict:
    """Load settings.json. Returns empty dict if missing."""
    path = get_settings_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, IOError):
        return {}


if __name__ == "__main__":
    # Terraform external data source output
    data = load_settings()
    print(json.dumps({
        "project_id": data.get("project_id", ""),
        "bucket_name": data.get("bucket_name", "")
    }))

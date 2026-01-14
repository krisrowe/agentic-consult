"""Tests for app.yaml configuration loading.

NOTE: conftest.py auto-sets CONSULT_CONFIG_DIR for every test.
Use the `config_dir` fixture to get the isolated config path.
"""
import yaml
import pytest
from agentic_consult.config import load_app_config


def test_load_app_config_default(monkeypatch):
    """
    Verify that the loader falls back to the package-default app.yaml
    when no user-level override is present.
    """
    # Ensure no environment variable override is set for this test
    monkeypatch.delenv("CONSULT_CONFIG_DIR", raising=False)

    data = load_app_config()

    # Assert that we got some standard data from the package default
    assert "gemini" in data
    assert "models" in data["gemini"]
    assert "default" in data["gemini"]["models"]


def test_load_app_config_user_override(config_dir):
    """
    Verify that a user-provided app.yaml in the config directory
    overrides the package defaults.
    """
    user_app_yaml = config_dir / "app.yaml"

    # Define a custom configuration
    custom_data = {
        "gemini": {
            "models": {
                "default": "my-custom-model",
                "available": ["my-custom-model", "other-model"]
            }
        },
        "precommit": {
            "allowed_emails": ["user@your-domain.com"],
            "check_git_identity": False
        }
    }

    with open(user_app_yaml, "w") as f:
        yaml.dump(custom_data, f)

    # Execute loader
    data = load_app_config()

    # Assertions: The returned data should match our custom override
    assert data["gemini"]["models"]["default"] == "my-custom-model"
    assert "user@your-domain.com" in data["precommit"]["allowed_emails"]
    assert data["precommit"]["check_git_identity"] is False

    # Verify it is a full replacement (logic in config.py prioritizes user file)
    # If the user file exists, the default file is never loaded/merged.
    assert len(data["precommit"]["allowed_emails"]) == 1

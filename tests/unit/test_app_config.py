import os
import yaml
import pytest
from pathlib import Path
from agentic_consult.config import load_app_config

@pytest.fixture
def mock_config_dir(tmp_path, monkeypatch):
    """Setup a temporary configuration directory and point the app to it."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setenv("CONSULT_CONFIG_DIR", str(config_dir))
    return config_dir

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

def test_load_app_config_user_override(mock_config_dir):
    """
    Verify that a user-provided app.yaml in the config directory 
    overrides the package defaults.
    """
    user_app_yaml = mock_config_dir / "app.yaml"
    
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

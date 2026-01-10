import os
import yaml
import pytest
from pathlib import Path
from jsonschema import ValidationError
from agentic_consult.config import load_app_config

@pytest.fixture
def mock_config_dir(tmp_path, monkeypatch):
    """Setup a temporary configuration directory."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setenv("CONSULT_CONFIG_DIR", str(config_dir))
    return config_dir

def test_load_app_config_rejects_additional_properties(mock_config_dir):
    """
    Verify that load_app_config raises ValidationError if additional 
    properties are present in app.yaml.
    """
    app_yaml = mock_config_dir / "app.yaml"
    
    # 1. Start with a minimal valid config (matching existing app.yaml structure)
    valid_data = {
        "gemini": {
            "models": {
                "default": "gemini-2.0-flash",
                "available": ["gemini-2.0-flash"]
            }
        }
    }
    
    with open(app_yaml, "w") as f:
        yaml.dump(valid_data, f)
        
    # Should pass initially (even if loose)
    data = load_app_config()
    assert data["gemini"]["models"]["default"] == "gemini-2.0-flash"
    
    # 2. Inject junk at root
    valid_data["junk_root"] = "should_fail"
    with open(app_yaml, "w") as f:
        yaml.dump(valid_data, f)
        
    # EXPECT FAILURE: This should raise ValidationError if schema is strict
    with pytest.raises(ValidationError):
        load_app_config()

def test_load_app_config_rejects_nested_additional_properties(mock_config_dir):
    """
    Verify that load_app_config raises ValidationError if additional 
    properties are present in nested objects.
    """
    app_yaml = mock_config_dir / "app.yaml"
    
    valid_data = {
        "gemini": {
            "models": {
                "default": "gemini-2.0-flash",
                "available": ["gemini-2.0-flash"],
                "junk_nested": "should_fail"
            }
        }
    }
    
    with open(app_yaml, "w") as f:
        yaml.dump(valid_data, f)
        
    # EXPECT FAILURE
    with pytest.raises(ValidationError):
        load_app_config()

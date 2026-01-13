import os
import json
from pathlib import Path
import pytest
import click
from agentic_consult.config import get_config_path, load_main_config, get_local_data_root
from agentic_consult.customers import get_active_customers_root

def test_default_settings_location(monkeypatch, tmp_path):
    """Confirm settings.json is in the standard XDG config location."""
    fake_config_dir = tmp_path / "config"
    fake_config_dir.mkdir()
    monkeypatch.setattr(click, "get_app_dir", lambda name: str(fake_config_dir))
    
    config_path = get_config_path()
    assert config_path == fake_config_dir / "settings.json"

def test_default_local_data_is_xdg(monkeypatch, tmp_path):
    """Verify local_data defaults to ~/.local/share/agentic-consult/."""
    fake_config_dir = tmp_path / "config"
    fake_config_dir.mkdir()
    monkeypatch.setattr(click, "get_app_dir", lambda name: str(fake_config_dir))
    
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    
    # Ensure no settings.json exists (default case)
    data_root = get_local_data_root()
    
    # Note: On Linux, standard XDG data is ~/.local/share/
    expected = fake_home / ".local" / "share" / "agentic-consult"
    assert data_root == expected

def test_local_data_folder_override(monkeypatch, tmp_path):
    """Verify settings.json 'local_data' override is respected."""
    fake_config_dir = tmp_path / "config"
    fake_config_dir.mkdir()
    monkeypatch.setattr(click, "get_app_dir", lambda name: str(fake_config_dir))
    
    custom_data_path = tmp_path / "custom_data"
    custom_data_path.mkdir()
    
    settings_file = fake_config_dir / "settings.json"
    with open(settings_file, "w") as f:
        json.dump({"local_data": str(custom_data_path)}, f)
        
    data_root = get_local_data_root()
    assert data_root == custom_data_path

def test_customer_settings_default_location(monkeypatch, tmp_path):
    """Verify customers folder is under default data root."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    
    fake_config_dir = tmp_path / "config"
    fake_config_dir.mkdir()
    monkeypatch.setattr(click, "get_app_dir", lambda name: str(fake_config_dir))
    
    customers_root = get_active_customers_root()
    expected = fake_home / ".local" / "share" / "agentic-consult" / "customers"
    assert customers_root == expected

def test_customer_settings_alt_location(monkeypatch, tmp_path):
    """Verify customers folder follows overridden local_data root."""
    fake_config_dir = tmp_path / "config"
    fake_config_dir.mkdir()
    monkeypatch.setattr(click, "get_app_dir", lambda name: str(fake_config_dir))
    
    custom_data_path = tmp_path / "custom_data"
    custom_data_path.mkdir()
    
    settings_file = fake_config_dir / "settings.json"
    with open(settings_file, "w") as f:
        json.dump({"local_data": str(custom_data_path)}, f)
        
    customers_root = get_active_customers_root()
    assert customers_root == custom_data_path / "customers"

def test_initialize_app_config_copies_file(monkeypatch, tmp_path):
    """Verify initialize_app_config copies the package default to the user config dir."""
    from agentic_consult.config import initialize_app_config
    import agentic_consult.config as config_pkg
    
    # 1. Mock get_config_path to point to our temp user dir
    fake_config_dir = tmp_path / "config"
    fake_config_dir.mkdir()
    
    def mock_get_config_path(filename=None):
        if filename:
            return fake_config_dir / filename
        return fake_config_dir / "settings.json"
        
    monkeypatch.setattr("agentic_consult.config.get_config_path", mock_get_config_path)
    
    # 2. Run initialization
    # It will use the real package app.yaml as source
    success, msg = initialize_app_config()
    
    assert success is True
    assert "Initialized default app.yaml" in msg
    assert (fake_config_dir / "app.yaml").exists()
    
    # 3. Verify content matches real package app.yaml
    real_pkg_path = Path(config_pkg.__file__).parent / "app.yaml"
    with open(real_pkg_path) as f:
        expected = f.read()
    with open(fake_config_dir / "app.yaml") as f:
        actual = f.read()
    assert actual == expected

def test_load_app_config_prioritizes_user_override(monkeypatch, tmp_path):
    """Verify load_app_config reads user's app.yaml if present."""
    from agentic_consult.config import load_app_config
    
    fake_config_dir = tmp_path / "config"
    fake_config_dir.mkdir()
    
    def mock_get_config_path(filename=None):
        return fake_config_dir / filename if filename else fake_config_dir / "settings.json"
        
    monkeypatch.setattr("agentic_consult.config.get_config_path", mock_get_config_path)
    
    # 1. Create a user override file
    user_yaml_content = """
gemini:
  debug: true
  models:
    default: user-override-model
    available: [user-override-model]
"""
    with open(fake_config_dir / "app.yaml", "w") as f:
        f.write(user_yaml_content)
        
    # 2. Mock validate_yaml
    monkeypatch.setattr("agentic_consult.config.validate_yaml", lambda d, s: None)
    
    config = load_app_config()
    
    # 3. Assert user value won
    assert config["gemini"]["models"]["default"] == "user-override-model"

def test_app_config_workflow_transition(monkeypatch, tmp_path):
    """
    Verify the full lifecycle: 
    1. Load default (Package)
    2. Initialize (Copy to User)
    3. Customize User Config
    4. Load custom (User)
    """
    from agentic_consult.config import initialize_app_config, load_app_config
    import yaml
    
    # Setup Mocks
    fake_config_dir = tmp_path / "config"
    fake_config_dir.mkdir()
    
    def mock_get_config_path(filename=None):
        return fake_config_dir / filename if filename else fake_config_dir / "settings.json"
        
    monkeypatch.setattr("agentic_consult.config.get_config_path", mock_get_config_path)
    monkeypatch.setattr("agentic_consult.config.validate_yaml", lambda d, s: None) 

    # 1. Verify Baseline (Package Default)
    assert not (fake_config_dir / "app.yaml").exists()
    
    initial_config = load_app_config()
    assert initial_config["gemini"]["models"]["default"] == "gemini-2.5-flash"
    
    # 2. Run Initialization
    success, msg = initialize_app_config()
    assert success is True
    assert (fake_config_dir / "app.yaml").exists()
    
    # 3. Modify User Config
    user_app_yaml = fake_config_dir / "app.yaml"
    with open(user_app_yaml, 'r') as f:
        data = yaml.safe_load(f)
    
    data["gemini"]["models"]["default"] = "user-custom-model-pro"
    
    with open(user_app_yaml, 'w') as f:
        yaml.dump(data, f)
        
    # 4. Verify Loading User Config
    new_config = load_app_config()
    assert new_config["gemini"]["models"]["default"] == "user-custom-model-pro"

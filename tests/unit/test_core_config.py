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

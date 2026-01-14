"""Tests for core config functionality.

NOTE: conftest.py auto-sets CONSULT_CONFIG_DIR for every test.
Use the `config_dir` fixture to get the isolated config path.
"""
import json
from pathlib import Path
import pytest
from agentic_consult.config import get_config_path, get_local_data_root
from agentic_consult.paths import get_settings_dir
from agentic_consult.customers import get_active_customers_root


def test_default_settings_location(config_dir):
    """Confirm settings.json path uses CONSULT_CONFIG_DIR (set by conftest)."""
    config_path = get_config_path()
    assert config_path == config_dir / "settings.json"


def test_default_local_data_is_xdg(monkeypatch, tmp_path):
    """Verify local_data defaults to ~/.local/share/agentic-consult/."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    # No settings.json exists, so get_local_data_root uses XDG default
    data_root = get_local_data_root()
    expected = fake_home / ".local" / "share" / "agentic-consult"
    assert data_root == expected


def test_local_data_folder_override(config_dir, tmp_path):
    """Verify settings.json 'local_data' override is respected."""
    custom_data_path = tmp_path / "custom_data"
    custom_data_path.mkdir()

    # Write settings.json to the config dir (already created by conftest)
    settings_file = config_dir / "settings.json"
    settings_file.write_text(json.dumps({"local_data": str(custom_data_path)}))

    data_root = get_local_data_root()
    assert data_root == custom_data_path


def test_customer_settings_default_location(monkeypatch, tmp_path):
    """Verify customers folder is under default data root."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    customers_root = get_active_customers_root()
    expected = fake_home / ".local" / "share" / "agentic-consult" / "customers"
    assert customers_root == expected


def test_customer_settings_alt_location(config_dir, tmp_path):
    """Verify customers folder follows overridden local_data root."""
    custom_data_path = tmp_path / "custom_data"
    custom_data_path.mkdir()

    settings_file = config_dir / "settings.json"
    settings_file.write_text(json.dumps({"local_data": str(custom_data_path)}))

    customers_root = get_active_customers_root()
    assert customers_root == custom_data_path / "customers"


def test_initialize_app_config_copies_file(config_dir):
    """Verify initialize_app_config copies the package default to the user config dir."""
    from agentic_consult.config import initialize_app_config
    import agentic_consult.config as config_pkg

    success, msg = initialize_app_config()

    assert success is True
    assert "Initialized default app.yaml" in msg

    user_app_yaml = config_dir / "app.yaml"
    assert user_app_yaml.exists()

    # Verify content matches real package app.yaml
    real_pkg_path = Path(config_pkg.__file__).parent / "app.yaml"
    assert user_app_yaml.read_text() == real_pkg_path.read_text()


def test_load_app_config_prioritizes_user_override(config_dir):
    """Verify load_app_config reads user's app.yaml if present."""
    from agentic_consult.config import load_app_config

    user_yaml_content = """
gemini:
  debug: true
  models:
    default: user-override-model
    available: [user-override-model]
"""
    user_app_yaml = config_dir / "app.yaml"
    user_app_yaml.write_text(user_yaml_content)

    config = load_app_config()
    assert config["gemini"]["models"]["default"] == "user-override-model"


def test_app_config_workflow_transition(config_dir):
    """
    Verify the full lifecycle:
    1. Load default (Package)
    2. Initialize (Copy to User)
    3. Customize User Config
    4. Load custom (User)
    """
    from agentic_consult.config import initialize_app_config, load_app_config
    import yaml

    user_app_yaml = config_dir / "app.yaml"

    # 1. Verify Baseline (Package Default)
    assert not user_app_yaml.exists()
    initial_config = load_app_config()
    assert initial_config["gemini"]["models"]["default"] == "gemini-2.5-flash"

    # 2. Run Initialization
    success, msg = initialize_app_config()
    assert success is True
    assert user_app_yaml.exists()

    # 3. Modify User Config
    data = yaml.safe_load(user_app_yaml.read_text())
    data["gemini"]["models"]["default"] = "user-custom-model-pro"
    user_app_yaml.write_text(yaml.dump(data))

    # 4. Verify Loading User Config
    new_config = load_app_config()
    assert new_config["gemini"]["models"]["default"] == "user-custom-model-pro"

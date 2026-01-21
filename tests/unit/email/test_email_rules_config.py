"""Tests for SDK email rules config operations.

Tests import/export of email.yaml with validation and backup.
Uses CONSULT_CONFIG_DIR isolation via conftest autouse fixture.
"""

import pytest
import yaml
from pydantic import ValidationError


def test_export_empty_config(config_dir):
    """Export returns empty structure when no config exists."""
    from agentic_consult.sdk.email.rules_config import export_email_config

    result = export_email_config()

    assert result == {"settings": None, "rules": [], "enable": [], "disable": []}


def test_export_existing_config(config_dir):
    """Export returns existing config content."""
    from agentic_consult.sdk.email.rules_config import export_email_config

    # Create a config file
    config_file = config_dir / "email.yaml"
    config_data = {
        "settings": {"timezone": "America/Chicago"},
        "rules": [{"id": "test-rule", "action": "archive"}]
    }
    config_file.write_text(yaml.dump(config_data))

    result = export_email_config()

    assert result["settings"]["timezone"] == "America/Chicago"
    assert len(result["rules"]) == 1
    assert result["rules"][0]["id"] == "test-rule"


def test_import_valid_config(config_dir):
    """Import writes valid config and returns success."""
    from agentic_consult.sdk.email.rules_config import import_email_config, export_email_config

    new_config = {
        "settings": {"timezone": "UTC"},
        "rules": [{"id": "new-rule", "action": "review"}]
    }

    result = import_email_config(new_config)

    assert result["status"] == "updated"
    assert "path" in result

    # Verify it was saved
    saved = export_email_config()
    assert saved["settings"]["timezone"] == "UTC"
    assert saved["rules"][0]["id"] == "new-rule"


def test_import_unchanged_config(config_dir):
    """Import returns unchanged status when content is identical."""
    from agentic_consult.sdk.email.rules_config import import_email_config

    config_data = {
        "rules": [{"id": "existing-rule", "action": "archive"}]
    }

    # First import
    import_email_config(config_data)

    # Second import with same data
    result = import_email_config(config_data)

    assert result["status"] == "unchanged"


def test_import_creates_backup(config_dir):
    """Import creates backup when overwriting existing config."""
    from agentic_consult.sdk.email.rules_config import import_email_config

    # Create initial config
    initial = {"rules": [{"id": "old-rule", "action": "archive"}]}
    import_email_config(initial)

    # Import different config
    updated = {"rules": [{"id": "new-rule", "action": "review"}]}
    result = import_email_config(updated)

    assert result["status"] == "updated"
    assert result.get("backup_path") is not None
    assert "replaced" in result["backup_path"]


def test_import_invalid_schema_fails(config_dir):
    """Import rejects config with unknown fields."""
    from agentic_consult.sdk.email.rules_config import import_email_config

    invalid_config = {
        "rules": [{"id": "bad-rule", "unknown_field": "value"}]
    }

    with pytest.raises(ValidationError):
        import_email_config(invalid_config)


def test_import_invalid_rule_missing_id(config_dir):
    """Import rejects rule without id."""
    from agentic_consult.sdk.email.rules_config import import_email_config

    invalid_config = {
        "rules": [{"action": "archive"}]  # Missing id
    }

    with pytest.raises(ValidationError):
        import_email_config(invalid_config)


def test_import_validates_settings_fields(config_dir):
    """Import rejects unknown settings fields."""
    from agentic_consult.sdk.email.rules_config import import_email_config

    invalid_config = {
        "settings": {"unknown_setting": "value"}
    }

    with pytest.raises(ValidationError):
        import_email_config(invalid_config)

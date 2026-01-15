"""Tests for cloud init command."""
import json
from click.testing import CliRunner
from agentic_consult.cli.cloud import cloud_init


def test_init_fails_without_project(cloud_config):
    """Init fails when no project can be resolved."""
    cloud_config("empty")
    runner = CliRunner()
    result = runner.invoke(cloud_init, ["--non-interactive"])
    assert result.exit_code != 0
    assert "Could not determine Project ID" in result.output


def test_init_fails_missing_secrets_non_interactive(cloud_config):
    """Init fails in non-interactive mode when secrets are missing."""
    cloud_config("labeled-project")
    runner = CliRunner()
    result = runner.invoke(cloud_init, ["--non-interactive"])
    assert result.exit_code != 0
    assert "gemini-api-key" in result.output


def test_init_creates_bucket_when_allowed(cloud_config, tmp_path):
    """Init creates bucket when --allow-create-bucket is passed."""
    provider = cloud_config("labeled-project")
    # Add secrets so we don't fail on those
    provider.secrets["gemini-api-key"] = {"project": "test-project-123", "value": "test-key"}
    provider.secrets["gmail-token"] = {"project": "test-project-123", "value": "{}"}

    runner = CliRunner()
    result = runner.invoke(cloud_init, [
        "--non-interactive",
        "--allow-create-bucket",
    ])

    assert result.exit_code == 0, f"Failed: {result.output}"
    assert "Creating gs://consult-data-test-project-123" in result.output
    assert "consult-data-test-project-123" in provider.buckets


def test_init_uses_existing_labeled_bucket(cloud_config, tmp_path):
    """Init uses existing labeled bucket without creating new one."""
    provider = cloud_config("full-setup")

    runner = CliRunner()
    result = runner.invoke(cloud_init, ["--non-interactive"])

    assert result.exit_code == 0, f"Failed: {result.output}"
    assert "Creating gs://" not in result.output
    assert "Ensuring consult-data-test-project-123 is labeled" in result.output


def test_init_requires_flag_to_change_bucket(cloud_config):
    """Init refuses to switch buckets without --allow-change-bucket."""
    provider = cloud_config("full-setup")

    runner = CliRunner()
    result = runner.invoke(cloud_init, [
        "--bucket", "different-bucket",
        "--non-interactive",
    ])

    assert result.exit_code != 0
    assert "already active" in result.output
    assert "--allow-change-bucket" in result.output


def test_init_switches_bucket_label_when_allowed(cloud_config, tmp_path):
    """Init can switch bucket labels with --allow-change-bucket."""
    provider = cloud_config("full-setup")
    # Create the new target bucket
    provider.buckets["new-bucket"] = {"project": "test-project-123", "labels": {}}

    runner = CliRunner()
    result = runner.invoke(cloud_init, [
        "--bucket", "new-bucket",
        "--allow-change-bucket",
        "--non-interactive",
    ])

    assert result.exit_code == 0, f"Failed: {result.output}"
    assert "Unlabeling consult-data-test-project-123" in result.output
    # Old bucket label removed
    assert provider.buckets["consult-data-test-project-123"]["labels"].get("agentic-consult") is None
    # New bucket labeled
    assert provider.buckets["new-bucket"]["labels"]["agentic-consult"] == "default"


def test_init_creates_secrets_when_provided(cloud_config, tmp_path):
    """Init creates secrets when values are provided."""
    provider = cloud_config("missing-secrets")

    # Create a fake token file
    token_file = tmp_path / "token.json"
    token_file.write_text('{"token": "secret"}')

    runner = CliRunner()
    result = runner.invoke(cloud_init, [
        "--gemini-api-key", "my-api-key",
        "--gmail-token-path", str(token_file),
        "--non-interactive",
    ])

    assert result.exit_code == 0, f"Failed: {result.output}"
    assert "Creating secret 'gemini-api-key'" in result.output
    assert "Creating secret 'gmail-token'" in result.output
    assert "gemini-api-key" in provider.secrets
    assert "gmail-token" in provider.secrets


def test_init_updates_existing_secrets(cloud_config, tmp_path):
    """Init updates secrets when they already exist."""
    provider = cloud_config("full-setup")

    runner = CliRunner()
    result = runner.invoke(cloud_init, [
        "--gemini-api-key", "new-api-key",
        "--non-interactive",
    ])

    assert result.exit_code == 0, f"Failed: {result.output}"
    assert "Updating secret 'gemini-api-key'" in result.output
    assert provider.secrets["gemini-api-key"]["value"] == b"new-api-key"


def test_init_saves_config(cloud_config, tmp_path):
    """Init saves project_id and bucket_name to config."""
    provider = cloud_config("full-setup")

    runner = CliRunner()
    result = runner.invoke(cloud_init, ["--non-interactive"])

    assert result.exit_code == 0, f"Failed: {result.output}"

    # Check config was saved (read from the isolated config dir)
    from agentic_consult.config import load_main_config
    config = load_main_config()
    assert config.get("project_id") == "test-project-123"
    assert config.get("bucket_name") == "consult-data-test-project-123"


def test_configured_proj_lacks_label(cloud_config, config_dir):
    """Init uses project_id from existing config when project has no label.

    This is the 'reattach' scenario: user already ran init before,
    config has project_id, but GCP project has no agentic-consult label.
    Init should still work using the saved project_id.
    """
    from agentic_consult.config import set_app_config_value, load_main_config

    # Setup: empty GCP (no labeled projects), but local config has project_id
    provider = cloud_config("empty")

    # Simulate existing config from a previous init
    set_app_config_value("project_id", "my-existing-project")

    # PRECONDITION: Verify config has project_id
    config = load_main_config()
    assert config.get("project_id") == "my-existing-project", "Precondition: config must have project_id"

    # Add the project and resources to the provider (they exist, just unlabeled)
    provider.projects["my-existing-project"] = {"labels": {}}  # No agentic-consult label
    provider.buckets["my-bucket"] = {"project": "my-existing-project", "labels": {"agentic-consult": "default"}}
    provider.secrets["gemini-api-key"] = {"project": "my-existing-project", "value": "key"}
    provider.secrets["gmail-token"] = {"project": "my-existing-project", "value": "{}"}

    # PRECONDITION: Verify project has NO agentic-consult label
    project_labels = provider.projects["my-existing-project"].get("labels", {})
    assert "agentic-consult" not in project_labels, "Precondition: project must NOT have agentic-consult label"

    # Run init
    runner = CliRunner()
    result = runner.invoke(cloud_init, ["--non-interactive"])

    assert result.exit_code == 0, f"Failed: {result.output}"
    assert "my-existing-project" in result.output

    # POSTCONDITION: Project still has no label (init doesn't add project labels)
    project_labels_after = provider.projects["my-existing-project"].get("labels", {})
    assert "agentic-consult" not in project_labels_after, "Postcondition: init should not add project label"


def test_configured_proj_not_found_in_gcp(cloud_config, config_dir):
    """Init fails when config has project_id but project doesn't exist in GCP.

    User must verify their access or use --project to switch to a different project.
    """
    from agentic_consult.config import set_app_config_value, load_main_config

    # Setup: empty GCP (no projects at all)
    provider = cloud_config("empty")

    # Config has a project_id that doesn't exist in GCP
    set_app_config_value("project_id", "ghost-project")

    # PRECONDITION: Verify config has project_id
    config = load_main_config()
    assert config.get("project_id") == "ghost-project", "Precondition: config must have project_id"

    # PRECONDITION: Project does NOT exist in provider
    assert "ghost-project" not in provider.projects, "Precondition: project must NOT exist in GCP"

    # Run init
    runner = CliRunner()
    result = runner.invoke(cloud_init, ["--non-interactive"])

    # Should fail with helpful message
    assert result.exit_code != 0, f"Should have failed but got: {result.output}"
    assert "ghost-project" in result.output
    assert "--project" in result.output  # Should advise user they can override


def test_project_override_updates_config(cloud_config, config_dir):
    """Init with --project override updates config after successful init.

    When user explicitly passes --project that differs from config,
    successful init should update config with the new project_id.
    """
    from agentic_consult.config import set_app_config_value, load_main_config

    # Setup: full GCP setup
    provider = cloud_config("full-setup")

    # Config has a DIFFERENT project_id than what we'll pass
    set_app_config_value("project_id", "old-project")

    # PRECONDITION: Verify config has old project_id
    config = load_main_config()
    assert config.get("project_id") == "old-project", "Precondition: config must have old project_id"

    # Run init with explicit --project override (test-project-123 exists in full-setup)
    runner = CliRunner()
    result = runner.invoke(cloud_init, [
        "--project", "test-project-123",
        "--non-interactive",
    ])

    assert result.exit_code == 0, f"Failed: {result.output}"

    # POSTCONDITION: Config should be updated with new project_id
    config_after = load_main_config()
    assert config_after.get("project_id") == "test-project-123", "Postcondition: config must have new project_id"

"""Tests for cloud config init command."""
import json
from click.testing import CliRunner
from agentic_consult.cli.cloud import cloud_init


def test_init_fails_without_project(cloud_config):
    """Init fails when no project can be resolved."""
    cloud_config("empty")
    runner = CliRunner()
    result = runner.invoke(cloud_init, ["--non-interactive", "--skip-terraform"])
    assert result.exit_code != 0
    assert "Could not determine Project ID" in result.output


def test_init_fails_missing_secrets_non_interactive(cloud_config):
    """Init fails in non-interactive mode when secrets are missing."""
    cloud_config("labeled-project")
    runner = CliRunner()
    result = runner.invoke(cloud_init, ["--non-interactive", "--skip-terraform"])
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
        "--skip-terraform"
    ])

    assert result.exit_code == 0, f"Failed: {result.output}"
    assert "Creating gs://consult-data-test-project-123" in result.output
    assert "consult-data-test-project-123" in provider.buckets


def test_init_uses_existing_labeled_bucket(cloud_config, tmp_path):
    """Init uses existing labeled bucket without creating new one."""
    provider = cloud_config("full-setup")

    runner = CliRunner()
    result = runner.invoke(cloud_init, ["--non-interactive", "--skip-terraform"])

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
        "--skip-terraform"
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
        "--skip-terraform"
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
        "--skip-terraform"
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
        "--skip-terraform"
    ])

    assert result.exit_code == 0, f"Failed: {result.output}"
    assert "Updating secret 'gemini-api-key'" in result.output
    assert provider.secrets["gemini-api-key"]["value"] == b"new-api-key"


def test_init_saves_config(cloud_config, tmp_path):
    """Init saves project_id and bucket_name to config."""
    provider = cloud_config("full-setup")

    runner = CliRunner()
    result = runner.invoke(cloud_init, ["--non-interactive", "--skip-terraform"])

    assert result.exit_code == 0, f"Failed: {result.output}"

    # Check config was saved (read from the isolated config dir)
    from agentic_consult.config import load_main_config
    config = load_main_config()
    assert config.get("project_id") == "test-project-123"
    assert config.get("bucket_name") == "consult-data-test-project-123"

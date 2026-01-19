"""Tests for cloud init SDK function."""
import pytest
from agentic_consult.cloud import cloud_init, InitOptions, InitContext


def test_init_fails_without_project(cloud_config):
    """Init fails when no project can be resolved."""
    provider = cloud_config("empty")
    options = InitOptions()
    context = InitContext()  # non-interactive

    result = cloud_init(provider, options, {}, context)

    assert not result.success
    assert "Could not determine Project ID" in result.error


def test_init_fails_missing_secrets_non_interactive(cloud_config):
    """Init fails in non-interactive mode when secrets are missing."""
    provider = cloud_config("labeled-project")
    options = InitOptions()
    context = InitContext()  # non-interactive

    result = cloud_init(provider, options, {}, context)

    assert not result.success
    assert "gemini-api-key" in result.error


def test_init_creates_bucket_when_allowed(cloud_config):
    """Init creates bucket when allow_create_bucket is set."""
    provider = cloud_config("labeled-project")
    # Add secrets so we don't fail on those
    provider.secrets["gemini-api-key"] = {"project": "test-project-123", "value": "test-key"}
    provider.secrets["gmail-token"] = {"project": "test-project-123", "value": "{}"}

    options = InitOptions(allow_create_bucket=True)
    context = InitContext()

    result = cloud_init(provider, options, {}, context)

    assert result.success, f"Failed: {result.error}"
    assert result.bucket_name == "consult-data-test-project-123"
    assert "consult-data-test-project-123" in provider.buckets
    assert any(op["op"] == "bucket_created" for op in result.operations)


def test_init_uses_existing_labeled_bucket(cloud_config):
    """Init uses existing labeled bucket without creating or re-labeling."""
    provider = cloud_config("full-setup")
    options = InitOptions()
    context = InitContext()

    result = cloud_init(provider, options, {}, context)

    assert result.success, f"Failed: {result.error}"
    # Should not have created or labeled bucket
    assert not any(op["op"] == "bucket_created" for op in result.operations)
    assert not any(op["op"] == "bucket_labeled" for op in result.operations)


def test_init_requires_flag_to_change_bucket(cloud_config):
    """Init refuses to switch buckets without allow_change_bucket."""
    provider = cloud_config("full-setup")
    options = InitOptions(bucket="different-bucket")
    context = InitContext()  # non-interactive, confirm returns False

    result = cloud_init(provider, options, {}, context)

    assert not result.success
    assert "already active" in result.error
    assert "--allow-change-bucket" in result.error


def test_init_switches_bucket_label_when_allowed(cloud_config):
    """Init can switch bucket labels with allow_change_bucket."""
    provider = cloud_config("full-setup")
    # Create the new target bucket
    provider.buckets["new-bucket"] = {"project": "test-project-123", "labels": {}}

    options = InitOptions(bucket="new-bucket", allow_change_bucket=True)
    context = InitContext()

    result = cloud_init(provider, options, {}, context)

    assert result.success, f"Failed: {result.error}"
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

    options = InitOptions(
        gemini_api_key="my-api-key",
        gmail_token_path=str(token_file),
    )
    context = InitContext()

    result = cloud_init(provider, options, {}, context)

    assert result.success, f"Failed: {result.error}"
    assert "gemini-api-key" in provider.secrets
    assert "gmail-token" in provider.secrets
    assert any(op["op"] == "secret_created" and op["secret"] == "gemini-api-key" for op in result.operations)
    assert any(op["op"] == "secret_created" and op["secret"] == "gmail-token" for op in result.operations)


def test_init_updates_existing_secrets(cloud_config):
    """Init updates secrets when they already exist."""
    provider = cloud_config("full-setup")

    options = InitOptions(gemini_api_key="new-api-key")
    context = InitContext()

    result = cloud_init(provider, options, {}, context)

    assert result.success, f"Failed: {result.error}"
    assert provider.secrets["gemini-api-key"]["value"] == b"new-api-key"
    assert any(op["op"] == "secret_updated" and op["secret"] == "gemini-api-key" for op in result.operations)


def test_init_returns_project_and_bucket(cloud_config):
    """Init returns project_id and bucket_name for config saving."""
    provider = cloud_config("full-setup")
    options = InitOptions()
    context = InitContext()

    result = cloud_init(provider, options, {}, context)

    assert result.success
    assert result.project_id == "test-project-123"
    assert result.bucket_name == "consult-data-test-project-123"


def test_configured_proj_lacks_label(cloud_config):
    """Init uses project_id from existing config when project has no label.

    This is the 'reattach' scenario: user already ran init before,
    config has project_id, but GCP project has no agentic-consult label.
    Init should still work using the saved project_id.
    """
    # Setup: empty GCP (no labeled projects)
    provider = cloud_config("empty")

    # Add the project and resources to the provider (they exist, just unlabeled)
    provider.projects["my-existing-project"] = {"labels": {}}  # No agentic-consult label
    provider.buckets["my-bucket"] = {"project": "my-existing-project", "labels": {"agentic-consult": "default"}}
    provider.secrets["gemini-api-key"] = {"project": "my-existing-project", "value": "key"}
    provider.secrets["gmail-token"] = {"project": "my-existing-project", "value": "{}"}

    # Existing config from a previous init
    existing_config = {"project_id": "my-existing-project"}

    options = InitOptions()
    context = InitContext()

    result = cloud_init(provider, options, existing_config, context)

    assert result.success, f"Failed: {result.error}"
    assert result.project_id == "my-existing-project"


def test_configured_proj_not_found_in_gcp(cloud_config):
    """Init fails when config has project_id but project doesn't exist in GCP.

    User must verify their access or use --project to switch to a different project.
    """
    # Setup: empty GCP (no projects at all)
    provider = cloud_config("empty")

    # Config has a project_id that doesn't exist in GCP
    existing_config = {"project_id": "ghost-project"}

    options = InitOptions()
    context = InitContext()

    result = cloud_init(provider, options, existing_config, context)

    # Should fail with helpful message
    assert not result.success
    assert "ghost-project" in result.error
    assert "--project" in result.error


def test_project_override_updates_result(cloud_config):
    """Init with project override returns new project_id.

    When user explicitly passes project that differs from config,
    successful init should return the new project_id.
    """
    # Setup: full GCP setup
    provider = cloud_config("full-setup")

    # Config has a DIFFERENT project_id than what we'll pass
    existing_config = {"project_id": "old-project"}

    # Explicit project override
    options = InitOptions(project="test-project-123")
    context = InitContext()

    result = cloud_init(provider, options, existing_config, context)

    assert result.success, f"Failed: {result.error}"
    assert result.project_id == "test-project-123"

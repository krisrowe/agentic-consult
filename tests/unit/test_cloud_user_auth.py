"""Tests for ./cloud user-auth commands."""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

# Add deploy/scripts to path for imports
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "deploy" / "scripts"))

from user_auth import cmd_status, cmd_init, cmd_export, generate_token, SECRET_ID


class MockArgs:
    """Mock argparse args."""
    def __init__(self, **kwargs):
        self.force = kwargs.get("force", False)
        self.format = kwargs.get("format", "yaml")
        self.quiet = kwargs.get("quiet", False)


def test_generate_token_length():
    """Generated token has expected length (base64 encoded)."""
    token = generate_token(32)
    # urlsafe_b64 of 32 bytes is ~43 chars
    assert len(token) >= 40


def test_generate_token_uniqueness():
    """Each generated token is unique."""
    tokens = [generate_token() for _ in range(10)]
    assert len(set(tokens)) == 10


def test_cmd_status_missing_token(cloud_config, capsys):
    """Status shows MISSING when no token exists."""
    provider = cloud_config("labeled-project")
    args = MockArgs()

    cmd_status(args, provider, "test-project-123")

    out = capsys.readouterr().out
    assert "MISSING" in out


@patch("user_auth.get_cloud_run_url")
def test_cmd_status_present_token(mock_url, cloud_config, capsys):
    """Status shows PRESENT when token exists."""
    mock_url.return_value = "https://consult-mcp-test.run.app"
    provider = cloud_config("labeled-project")
    provider.secrets[SECRET_ID] = {"project": "test-project-123", "value": "test-token-123"}
    args = MockArgs()

    cmd_status(args, provider, "test-project-123")

    out = capsys.readouterr().out
    assert "PRESENT" in out
    assert "test-project-123" in out


def test_cmd_init_creates_token(cloud_config, capsys):
    """Init creates a new token in Secret Manager."""
    provider = cloud_config("labeled-project")
    args = MockArgs()

    cmd_init(args, provider, "test-project-123")

    # Token should be created
    assert SECRET_ID in provider.secrets
    token = provider.secrets[SECRET_ID]["value"]
    assert len(token) >= 40

    out = capsys.readouterr().out
    assert "Created access token" in out


def test_cmd_init_refuses_overwrite_without_force(cloud_config):
    """Init refuses to overwrite existing token without --force."""
    provider = cloud_config("labeled-project")
    provider.secrets[SECRET_ID] = {"project": "test-project-123", "value": "existing-token"}
    args = MockArgs(force=False)

    with pytest.raises(SystemExit) as exc_info:
        cmd_init(args, provider, "test-project-123")

    assert exc_info.value.code == 1


def test_cmd_init_overwrites_with_force(cloud_config, capsys):
    """Init overwrites existing token with --force."""
    provider = cloud_config("labeled-project")
    provider.secrets[SECRET_ID] = {"project": "test-project-123", "value": "old-token"}
    args = MockArgs(force=True)

    cmd_init(args, provider, "test-project-123")

    # Token should be replaced
    new_token = provider.secrets[SECRET_ID]["value"]
    assert new_token != "old-token"
    assert len(new_token) >= 40


@patch("user_auth.get_cloud_run_url")
def test_cmd_export_yaml_format(mock_url, cloud_config, capsys):
    """Export outputs YAML format by default."""
    mock_url.return_value = "https://consult-mcp-test.run.app"
    provider = cloud_config("labeled-project")
    provider.secrets[SECRET_ID] = {"project": "test-project-123", "value": "my-secret-token"}
    args = MockArgs(format="yaml", quiet=True)

    cmd_export(args, provider, "test-project-123")

    out = capsys.readouterr().out
    assert "url: https://consult-mcp-test.run.app" in out
    assert "access_token: my-secret-token" in out


@patch("user_auth.get_cloud_run_url")
def test_cmd_export_json_format(mock_url, cloud_config, capsys):
    """Export outputs JSON when --format=json."""
    mock_url.return_value = "https://consult-mcp-test.run.app"
    provider = cloud_config("labeled-project")
    provider.secrets[SECRET_ID] = {"project": "test-project-123", "value": "my-secret-token"}
    args = MockArgs(format="json", quiet=True)

    cmd_export(args, provider, "test-project-123")

    out = capsys.readouterr().out
    assert '"url":' in out
    assert '"access_token":' in out
    assert "https://consult-mcp-test.run.app" in out


@patch("user_auth.get_cloud_run_url")
def test_cmd_export_fails_no_token(mock_url, cloud_config):
    """Export fails when no token exists."""
    mock_url.return_value = "https://consult-mcp-test.run.app"
    provider = cloud_config("labeled-project")
    args = MockArgs()

    with pytest.raises(SystemExit) as exc_info:
        cmd_export(args, provider, "test-project-123")

    assert exc_info.value.code == 1


@patch("user_auth.get_cloud_run_url")
def test_cmd_export_fails_no_url(mock_url, cloud_config):
    """Export fails when Cloud Run service not deployed."""
    mock_url.return_value = None  # Service not found
    provider = cloud_config("labeled-project")
    provider.secrets[SECRET_ID] = {"project": "test-project-123", "value": "token"}
    args = MockArgs()

    with pytest.raises(SystemExit) as exc_info:
        cmd_export(args, provider, "test-project-123")

    assert exc_info.value.code == 1

"""Test that terraform configuration is valid.

This test downloads terraform providers from the public HashiCorp registry
(no GCP auth needed) and validates our .tf files for syntax and consistency.

Catches: bad HCL syntax, invalid references, type mismatches, missing required args.
Does NOT check: whether GCP resources actually exist.
"""
import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def mock_config(tmp_path, monkeypatch):
    """Setup temporary config with fake project/bucket values.

    Both project_id and bucket_name are stored in config.
    The 'resolve' command reads from config only (no network).
    See deploy/DESIGN.md "Testing" section for rationale.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text(json.dumps({
        "project_id": "fake-project-123",
        "bucket_name": "fake-bucket-456"
    }))
    monkeypatch.setenv("CONSULT_CONFIG_DIR", str(config_dir))
    return config_dir


def test_terraform_validates(mock_config):
    """Verify terraform config passes init and validate."""
    tf_dir = Path(__file__).parent.parent.parent / "deploy" / "terraform"

    # Init downloads providers from public registry (no auth needed)
    result = subprocess.run(
        ["terraform", "init", "-backend=false", "-input=false"],
        cwd=tf_dir,
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"terraform init failed:\n{result.stderr}"

    # Validate checks syntax and internal consistency
    result = subprocess.run(
        ["terraform", "validate"],
        cwd=tf_dir,
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"terraform validate failed:\n{result.stderr}"

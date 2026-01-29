"""Tests for SDK scanner local_username step."""
import os
import subprocess
from unittest.mock import patch
from agentic_consult.sdk.scanner.core import run_scan


def test_local_username_detected_in_staged(tmp_path):
    """Local username in staged content is flagged."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

    username = os.environ.get("USER") or os.environ.get("USERNAME") or "testuser"

    (repo / "config.txt").write_text(f"path: /home/{username}/secrets")
    subprocess.run(["git", "-C", str(repo), "add", "config.txt"], check=True)

    with patch.dict(os.environ, {"USER": username}):
        report = run_scan(str(repo), only_check="local_username")

    check = next(c for c in report.checks if c.name == "Local username")
    assert not check.passed
    assert any(username in f for f in check.findings)


def test_local_username_not_flagged_when_absent(tmp_path):
    """Clean content without username passes."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

    (repo / "config.txt").write_text("path: /opt/app/data")
    subprocess.run(["git", "-C", str(repo), "add", "config.txt"], check=True)

    with patch.dict(os.environ, {"USER": "uniquetestuser12345"}):
        report = run_scan(str(repo), only_check="local_username")

    check = next(c for c in report.checks if c.name == "Local username")
    assert check.passed


def test_local_username_skips_when_no_env_var(tmp_path):
    """Check skips when no USER/USERNAME env var."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

    (repo / "file.txt").write_text("some content")
    subprocess.run(["git", "-C", str(repo), "add", "file.txt"], check=True)

    env = os.environ.copy()
    env.pop("USER", None)
    env.pop("USERNAME", None)

    with patch.dict(os.environ, env, clear=True):
        report = run_scan(str(repo), only_check="local_username")

    check = next(c for c in report.checks if c.name == "Local username")
    assert check.skipped

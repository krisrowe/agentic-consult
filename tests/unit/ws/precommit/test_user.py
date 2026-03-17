"""Tests for SDK scanner user module - via run_scan(only_check='user')."""
import subprocess
import pytest
from agentic_consult.sdk.scanner.core import run_scan, MissingUserConfigError

# Check names that belong to the user module
USER_CHECK_NAMES = {
    "Sensitive patterns in uncommitted",
    "Sensitive patterns in history",
    "Sensitive patterns in commits",
    "Stash entries",
    "Reflog patterns",
    "Sensitive filenames",
    "Branch names",
    "Tag names",
}


def create_patterns_config(config_dir, patterns):
    """Create sensitive-patterns.yaml with given patterns."""
    yaml_content = "patterns:\n"
    for p in patterns:
        yaml_content += f'  - pattern: "{p}"\n'
    (config_dir / "sensitive-patterns.yaml").write_text(yaml_content)


def assert_only_user_module(report):
    """Assert report contains only user checks (plus Git repository)."""
    for check in report.checks:
        assert check.name == "Git repository" or check.name in USER_CHECK_NAMES, \
            f"Unexpected check '{check.name}' - only user module should run"


def test_detects_pattern_in_staged_content(tmp_path, config_dir):
    """Patterns in staged (git add) content are detected."""
    create_patterns_config(config_dir, ["SecretWord"])

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

    (repo / "file.txt").write_text("Contains SecretWord here")
    subprocess.run(["git", "-C", str(repo), "add", "file.txt"], check=True)

    report = run_scan(str(repo), only_check="user")

    # Verify only user module ran
    assert_only_user_module(report)

    # Verify finding detected
    assert report.failed
    uncommitted = next(c for c in report.checks if c.name == "Sensitive patterns in uncommitted")
    assert not uncommitted.passed
    assert any("SecretWord" in f for f in uncommitted.findings)


def test_detects_pattern_in_unstaged_content(tmp_path, config_dir):
    """Patterns in unstaged modifications are detected."""
    create_patterns_config(config_dir, ["SecretWord"])

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)

    # Commit clean file first
    (repo / "file.txt").write_text("clean content")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "--no-verify", "-m", "init"], check=True, capture_output=True)

    # Modify without staging
    (repo / "file.txt").write_text("now has SecretWord")

    report = run_scan(str(repo), only_check="user")

    assert_only_user_module(report)
    assert report.failed
    uncommitted = next(c for c in report.checks if c.name == "Sensitive patterns in uncommitted")
    assert not uncommitted.passed


def test_detects_pattern_in_untracked_file(tmp_path, config_dir):
    """Patterns in untracked files detected when --untracked is opted in."""
    create_patterns_config(config_dir, ["SecretWord"])

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

    # Create file but don't stage it
    (repo / "newfile.txt").write_text("Contains SecretWord")

    # Without include_untracked, untracked files are not scanned
    report = run_scan(str(repo), only_check="user")
    assert not report.failed

    # With include_untracked, the pattern is caught
    report = run_scan(str(repo), only_check="user", include_untracked=True)

    assert_only_user_module(report)
    assert report.failed
    uncommitted = next(c for c in report.checks if c.name == "Sensitive patterns in uncommitted")
    assert not uncommitted.passed


def test_detects_pattern_in_git_history(tmp_path, config_dir):
    """Patterns in committed git history are detected (deep mode)."""
    create_patterns_config(config_dir, ["SecretWord"])

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)

    # Commit file with sensitive content
    (repo / "file.txt").write_text("Has SecretWord in it")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "--no-verify", "-m", "add file"], check=True, capture_output=True)

    # Replace with clean content and commit again
    (repo / "file.txt").write_text("Now clean")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "--no-verify", "-m", "clean up"], check=True, capture_output=True)

    # History should still find the old content
    report = run_scan(str(repo), deep=True, only_check="user")

    assert_only_user_module(report)
    assert report.failed
    history = next(c for c in report.checks if c.name == "Sensitive patterns in history")
    assert not history.passed
    assert any("SecretWord" in f for f in history.findings)


def test_skips_when_no_config(tmp_path):
    """User checks skip (not fail) when no config file exists."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

    (repo / "file.txt").write_text("Contains SecretWord here")
    subprocess.run(["git", "-C", str(repo), "add", "file.txt"], check=True)

    report = run_scan(str(repo), only_check="user")

    # Should not fail - just skip
    assert not report.failed
    uncommitted = next(c for c in report.checks if c.name == "Sensitive patterns in uncommitted")
    assert uncommitted.skipped


def test_errors_when_no_config_and_required(tmp_path):
    """MissingUserConfigError raised when require_user_config=True and no config."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

    with pytest.raises(MissingUserConfigError):
        run_scan(str(repo), require_user_config=True)


def test_succeeds_when_config_exists_and_required(tmp_path, config_dir):
    """require_user_config=True succeeds when config file exists."""
    create_patterns_config(config_dir, ["SecretWord"])

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

    (repo / "file.txt").write_text("clean content")
    subprocess.run(["git", "-C", str(repo), "add", "file.txt"], check=True)

    # Should not raise - config exists
    report = run_scan(str(repo), require_user_config=True, only_check="user")
    assert not report.failed

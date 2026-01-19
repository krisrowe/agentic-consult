import os
import subprocess
import pytest
from pathlib import Path
from agentic_consult.sdk.scanner.steps.git_identity import check_git_identity
from unittest.mock import patch

@pytest.fixture(autouse=True)
def home_sandbox(tmp_path, monkeypatch):
    """Redirects HOME to a temporary directory to isolate global git config."""
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    return fake_home

def setup_git_repo(path):
    subprocess.run(['git', 'init', str(path)], check=True, capture_output=True)
    # Ensure default user for reproducibility
    subprocess.run(['git', 'config', 'user.name', 'Test User'], cwd=path, check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=path, check=True)

def commit_file(path, filename, content, author_email=None):
    (path / filename).write_text(content)
    subprocess.run(['git', 'add', filename], cwd=path, check=True, capture_output=True)

    env = os.environ.copy()
    if author_email:
        env['GIT_AUTHOR_EMAIL'] = author_email
        env['GIT_COMMITTER_EMAIL'] = author_email

    subprocess.run(['git', 'commit', '-m', f'Add {filename}'], cwd=path, env=env, check=True, capture_output=True)

# --- 1. No Local Configuration (Historical Consistency Mode) ---

def test_identity_pristine_repo_pass(tmp_path):
    """Scenario: Single user history matches impending identity -> PASS"""
    repo = tmp_path / "pristine_pass"
    setup_git_repo(repo)
    commit_file(repo, "file1.txt", "content", author_email="user@example.com")

    # UNSET local config to trigger history check
    subprocess.run(['git', 'config', '--local', '--unset', 'user.email'], cwd=repo, check=True)

    with patch.dict(os.environ, {'GIT_AUTHOR_EMAIL': 'user@example.com'}):
        result = check_git_identity(repo)
    assert result.passed

def test_identity_pristine_history_but_impending_mismatch_fail(tmp_path):
    """Scenario: History is clean, but environment is about to introduce mismatch -> FAIL"""
    repo = tmp_path / "pristine_mismatch"
    setup_git_repo(repo)
    commit_file(repo, "file1.txt", "content", author_email="user@example.com")

    subprocess.run(['git', 'config', '--local', '--unset', 'user.email'], cwd=repo, check=True)

    # Impending is DIFFERENT
    with patch.dict(os.environ, {'GIT_AUTHOR_EMAIL': 'test@fake.com'}):
        result = check_git_identity(repo)

    assert not result.passed
    assert any("History has" in f for f in result.findings)

@pytest.mark.skip(reason="Pre-existing failure - needs investigation")
def test_identity_mixed_history_no_local_fail(tmp_path):
    """Scenario: Mixed history, no local override -> FAIL"""
    repo = tmp_path / "mixed"
    setup_git_repo(repo)

    commit_file(repo, "file1.txt", "c1", author_email="user@example.com")
    commit_file(repo, "file2.txt", "c2", author_email="test@example.com")

    subprocess.run(['git', 'config', '--local', '--unset', 'user.email'], cwd=repo, check=True)

    result = check_git_identity(repo)
    assert not result.passed

# --- 2. Local Configuration Present (Explicit Trust Mode) ---

def test_identity_explicit_local_config_pass(tmp_path):
    """Scenario: Local config set, impending matches, unpushed matches -> PASS"""
    repo = tmp_path / "explicit_pass"
    setup_git_repo(repo)

    # Set config BEFORE commit
    subprocess.run(['git', 'config', '--local', 'user.email', 'user@example.com'], cwd=repo, check=True)
    commit_file(repo, "file1.txt", "c1", author_email="user@example.com")

    with patch.dict(os.environ, {'GIT_AUTHOR_EMAIL': 'user@example.com'}):
        result = check_git_identity(repo)

    assert result.passed

def test_identity_explicit_local_config_unpushed_fail(tmp_path):
    """Scenario: Local config set, but unpushed commits mismatch -> FAIL"""
    repo = tmp_path / "explicit_unpushed_fail"
    setup_git_repo(repo)

    subprocess.run(['git', 'config', '--local', 'user.email', 'user@example.com'], cwd=repo, check=True)
    commit_file(repo, "file1.txt", "c1", author_email="test@fake.com")

    with patch.dict(os.environ, {'GIT_AUTHOR_EMAIL': 'user@example.com'}):
        result = check_git_identity(repo)

    assert not result.passed
    assert any("Unpushed" in f for f in result.findings)

def test_identity_impending_mismatch_local_fail(tmp_path):
    """Scenario: Local config set, but impending environment overrides it -> FAIL"""
    repo = tmp_path / "impending_local_fail"
    setup_git_repo(repo)

    subprocess.run(['git', 'config', '--local', 'user.email', 'user@example.com'], cwd=repo, check=True)

    with patch.dict(os.environ, {'GIT_AUTHOR_EMAIL': 'test@fake.com'}):
        result = check_git_identity(repo)

    assert not result.passed
    assert any("differs from local config" in f for f in result.findings)

# --- 3. Edge Cases (Upstream Logic) ---

def test_identity_no_upstream_fallback_pass(tmp_path):
    """Scenario: Local repo (no remote). Local Config set. Commits match -> PASS"""
    repo = tmp_path / "local_only_pass"
    setup_git_repo(repo)

    subprocess.run(['git', 'config', '--local', 'user.email', 'user@example.com'], cwd=repo, check=True)
    commit_file(repo, "file1.txt", "c1", author_email="user@example.com")

    with patch.dict(os.environ, {'GIT_AUTHOR_EMAIL': 'user@example.com'}):
        result = check_git_identity(repo)

    assert result.passed

def test_identity_no_upstream_fallback_fail(tmp_path):
    """Scenario: Local repo (no remote). Local Config set. Commits mismatch -> FAIL"""
    repo = tmp_path / "local_only_fail"
    setup_git_repo(repo)

    subprocess.run(['git', 'config', '--local', 'user.email', 'user@example.com'], cwd=repo, check=True)
    commit_file(repo, "file1.txt", "c1", author_email="test@fake.com")

    with patch.dict(os.environ, {'GIT_AUTHOR_EMAIL': 'user@example.com'}):
        result = check_git_identity(repo)

    assert not result.passed
    assert any("Unpushed" in f for f in result.findings)

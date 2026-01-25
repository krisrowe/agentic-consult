"""Tests for precommit hook detection and installation.

Git global hooks require core.hooksPath to be configured.
Without it, no global hooks fire - only local .git/hooks/.

We use ~/.config/git/hooks as our "conventional" location.
Users may have a "custom" location already configured.
"""

import stat
import subprocess
from pathlib import Path

import pytest

from agentic_consult.sdk.hooks import get_hook_status, install_hook


@pytest.fixture
def isolated_git(tmp_path, monkeypatch):
    """Isolate HOME and git config to temp directory."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / ".gitconfig"))
    return tmp_path


@pytest.fixture
def git_repo(isolated_git):
    """Create isolated git repo for commit tests."""
    repo = isolated_git / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    return repo


def set_hooks_path(path: Path):
    subprocess.run(["git", "config", "--global", "core.hooksPath", str(path)], check=True, capture_output=True)


def make_hook(hook_path: Path, content: str):
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    hook_path.write_text(content)
    hook_path.chmod(0o755)


def commit(repo: Path):
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "add", "f.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "x"], cwd=repo, check=True, capture_output=True)


class TestHookFires:
    """Verify hooks actually run during commit."""

    def test_hook_fires_at_configured_path(self, isolated_git, git_repo):
        marker = isolated_git / "fired.txt"
        hooks_dir = isolated_git / "hooks"
        make_hook(hooks_dir / "pre-commit", f"#!/bin/sh\ntouch {marker}")
        set_hooks_path(hooks_dir)

        commit(git_repo)

        assert marker.exists()

    def test_hook_at_conventional_path_needs_config(self, isolated_git, git_repo):
        """Hook at conventional path does NOT fire without core.hooksPath."""
        marker = isolated_git / "fired.txt"
        conventional = isolated_git / ".config" / "git" / "hooks"
        make_hook(conventional / "pre-commit", f"#!/bin/sh\ntouch {marker}")
        # NOT setting core.hooksPath

        commit(git_repo)

        assert not marker.exists()

    def test_conventional_ignored_when_custom_configured(self, isolated_git, git_repo):
        marker = isolated_git / "fired.txt"
        conventional = isolated_git / ".config" / "git" / "hooks"
        custom = isolated_git / "custom-hooks"
        custom.mkdir()

        make_hook(conventional / "pre-commit", f"#!/bin/sh\ntouch {marker}")
        set_hooks_path(custom)  # points to empty dir

        commit(git_repo)

        assert not marker.exists()


class TestGetHookStatus:

    def test_not_installed_when_no_hooks_path(self, isolated_git):
        status = get_hook_status()
        assert status["installed"] is False

    def test_not_installed_when_hooks_path_empty(self, isolated_git):
        hooks_dir = isolated_git / "hooks"
        hooks_dir.mkdir()
        set_hooks_path(hooks_dir)

        status = get_hook_status()
        assert status["installed"] is False

    def test_not_installed_when_hook_lacks_consult(self, isolated_git):
        hooks_dir = isolated_git / "hooks"
        make_hook(hooks_dir / "pre-commit", "#!/bin/sh\necho hi")
        set_hooks_path(hooks_dir)

        status = get_hook_status()
        assert status["installed"] is False

    def test_installed_when_consult_hook_at_configured_path(self, isolated_git):
        hooks_dir = isolated_git / "hooks"
        make_hook(hooks_dir / "pre-commit", "#!/bin/sh\nconsult precommit .")
        set_hooks_path(hooks_dir)

        status = get_hook_status()
        assert status["installed"] is True
        assert status["location"] == str(hooks_dir / "pre-commit")

    def test_installed_when_devws_hook_at_configured_path(self, isolated_git):
        hooks_dir = isolated_git / "hooks"
        make_hook(hooks_dir / "pre-commit", "#!/bin/sh\ndevws precommit")
        set_hooks_path(hooks_dir)

        status = get_hook_status()
        assert status["installed"] is True


class TestInstallHook:

    def test_installs_and_configures_hooks_path(self, isolated_git):
        result = install_hook()

        assert result["success"] is True
        hook = Path(result["path"])
        assert hook.exists()
        assert "consult precommit" in hook.read_text()
        assert hook.stat().st_mode & stat.S_IXUSR

    def test_installs_to_custom_path_when_configured(self, isolated_git):
        custom = isolated_git / "my-hooks"
        custom.mkdir()
        set_hooks_path(custom)

        result = install_hook()

        assert result["success"] is True
        assert result["path"] == str(custom / "pre-commit")

    def test_is_idempotent(self, isolated_git):
        first = install_hook()
        second = install_hook()

        assert first["success"] is True
        assert second["success"] is True
        assert "already installed" in second["message"]

    def test_refuses_to_overwrite_foreign_hook(self, isolated_git):
        hooks_dir = isolated_git / "hooks"
        make_hook(hooks_dir / "pre-commit", "#!/bin/sh\nmy-other-tool")
        set_hooks_path(hooks_dir)

        result = install_hook()

        assert result["success"] is False
        assert "Manual merge" in result["message"]
        assert "my-other-tool" in (hooks_dir / "pre-commit").read_text()

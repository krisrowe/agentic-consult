"""Git hook detection and installation utilities.

Global hooks require core.hooksPath to be configured.
We use ~/.config/git/hooks as our conventional location.
"""

import os
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional


HOOK_SCRIPT = """#!/bin/sh
# Consult pre-commit hook
# Runs sensitive data scanning before commit

consult precommit .
"""

CONVENTIONAL_HOOKS_DIR = Path.home() / ".config" / "git" / "hooks"


def get_hook_status() -> Dict[str, Any]:
    """Get global precommit hook status.

    Returns installed=True only if core.hooksPath is configured
    AND that path contains a consult/devws hook.

    Returns:
        {
            "installed": bool,
            "location": str | None,
        }
    """
    configured_path = _get_core_hooks_path()
    if not configured_path:
        return {"installed": False, "location": None}

    hook_path = Path(configured_path) / "pre-commit"
    if _has_consult_hook(hook_path):
        return {"installed": True, "location": str(hook_path)}

    return {"installed": False, "location": None}


def _has_consult_hook(path: Path) -> bool:
    """Check if hook file exists and contains consult/devws."""
    if not path.exists():
        return False
    try:
        content = path.read_text()
        return "consult" in content or "devws" in content
    except Exception:
        return False


def _get_core_hooks_path() -> Optional[str]:
    """Get global core.hooksPath config value."""
    try:
        result = subprocess.run(
            ["git", "config", "--global", "core.hooksPath"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return os.path.expanduser(result.stdout.strip())
    except Exception:
        pass
    return None


def install_hook() -> Dict[str, Any]:
    """Install consult pre-commit hook globally.

    If core.hooksPath is configured, installs there.
    Otherwise, sets core.hooksPath to conventional location and installs.

    Returns:
        {"success": bool, "message": str, "path": str | None}
    """
    configured = _get_core_hooks_path()
    if configured:
        hook_dir = Path(configured)
    else:
        hook_dir = CONVENTIONAL_HOOKS_DIR
        try:
            subprocess.run(
                ["git", "config", "--global", "core.hooksPath", str(hook_dir)],
                check=True,
                capture_output=True,
                timeout=5
            )
        except subprocess.CalledProcessError as e:
            return {"success": False, "message": f"Failed to set core.hooksPath: {e}", "path": None}

    hook_path = hook_dir / "pre-commit"

    if hook_path.exists():
        content = hook_path.read_text()
        if "consult" in content or "devws" in content:
            return {"success": True, "message": "Hook already installed", "path": str(hook_path)}
        return {
            "success": False,
            "message": f"Hook exists at {hook_path} but doesn't contain consult. Manual merge required.",
            "path": str(hook_path)
        }

    hook_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        hook_path.write_text(HOOK_SCRIPT)
        hook_path.chmod(0o755)
        return {"success": True, "message": f"Installed hook at {hook_path}", "path": str(hook_path)}
    except Exception as e:
        return {"success": False, "message": f"Failed to write hook: {e}", "path": str(hook_path)}

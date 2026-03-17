"""Git identity check - ensures consistent committer identity."""

import re
import subprocess
from pathlib import Path
from typing import List

from agentic_consult.config import load_main_config
from ..utils import CheckResult


def check_git_identity(repo_path: str) -> CheckResult:
    """Ensure committer identity is consistent with repo history or local config."""
    path = Path(repo_path)

    try:
        # Get impending commit email
        res = subprocess.run(
            ['git', 'var', 'GIT_AUTHOR_IDENT'],
            cwd=path, capture_output=True, text=True
        )
        if res.returncode != 0:
            return CheckResult("Git identity", True, [], skipped=True,
                              info="Not a git repo or can't determine identity")

        match = re.search(r'<(.*)>', res.stdout)
        if not match:
            return CheckResult("Git identity", True, [], skipped=True,
                              info="Could not parse git identity")
        impending_email = match.group(1).strip()

        # Check for local config
        local_check = subprocess.run(
            ['git', 'config', '--local', '--get', 'user.email'],
            cwd=path, capture_output=True, text=True
        )
        has_local_config = (local_check.returncode == 0)
        local_email = local_check.stdout.strip() if has_local_config else None

        # If local config exists, verify consistency
        if has_local_config:
            if impending_email != local_email:
                return CheckResult("Git identity", False, [
                    f"Impending '{impending_email}' differs from local config '{local_email}'"
                ])

            # Check unpushed commits match local email
            unpushed_emails = set()
            try:
                res = subprocess.run(
                    ['git', 'log', '@{u}..HEAD', '--format=%ae'],
                    cwd=path, capture_output=True, text=True, check=True
                )
                unpushed_emails.update(e.strip() for e in res.stdout.splitlines() if e.strip())
            except subprocess.CalledProcessError:
                # No upstream - check all commits
                try:
                    res = subprocess.run(
                        ['git', 'log', '--format=%ae'],
                        cwd=path, capture_output=True, text=True, check=True
                    )
                    unpushed_emails.update(e.strip() for e in res.stdout.splitlines() if e.strip())
                except subprocess.CalledProcessError:
                    pass

            if unpushed_emails:
                mismatches = unpushed_emails - {local_email}
                if mismatches:
                    return CheckResult("Git identity", False, [
                        f"Unpushed commits have different identity: {mismatches}"
                    ])

            return CheckResult("Git identity", True)

        # No local config - history must match impending email
        res = subprocess.run(
            ['git', 'log', '--format=%ae'],
            cwd=path, capture_output=True, text=True
        )
        if res.returncode == 0:
            history_emails = set(e.strip() for e in res.stdout.splitlines() if e.strip())

            if not history_emails or history_emails == {impending_email}:
                return CheckResult("Git identity", True)

            # Check for override setting
            settings = load_main_config()
            if settings.get('precommit', {}).get('git_local_user_identity_optional', False):
                return CheckResult("Git identity", True)

            return CheckResult("Git identity", False, [
                f"History has {history_emails}, impending is '{impending_email}'",
                f"Fix: git config user.email {impending_email}",
                f"Or: consult config set precommit.git_local_user_identity_optional true"
            ])

        return CheckResult("Git identity", True)

    except Exception as e:
        return CheckResult("Git identity", True, [], skipped=True,
                          info=f"Check failed: {e}")


def run_checks(repo_path: str, deep: bool = False, **kwargs) -> List[CheckResult]:
    """Run git identity check. Standard step interface."""
    return [check_git_identity(repo_path)]

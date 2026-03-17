"""Local username check - derived from $USER env var."""

import os
from typing import List

from ..utils import CheckResult, run_cmd, DIFF_METADATA_FILTER


def check_local_username(repo_path: str, include_untracked: bool = False) -> CheckResult:
    """Check for local username in uncommitted content."""
    username = os.environ.get("USER") or os.environ.get("USERNAME")

    if not username:
        return CheckResult("Local username", True, [], skipped=True,
                          info="No USER/USERNAME env var")

    findings = []

    cmd = f"git diff --cached -U0 | {DIFF_METADATA_FILTER} | grep -F '{username}'"
    rc, stdout, _ = run_cmd(cmd, repo_path)
    if rc == 0 and stdout.strip():
        for line in stdout.strip().split("\n")[:5]:
            findings.append(f"staged: {line[:100]}")

    cmd = f"git diff -U0 | {DIFF_METADATA_FILTER} | grep -F '{username}'"
    rc, stdout, _ = run_cmd(cmd, repo_path)
    if rc == 0 and stdout.strip():
        for line in stdout.strip().split("\n")[:5]:
            findings.append(f"unstaged: {line[:100]}")

    # Untracked files aren't staged and won't be in the commit —
    # scanning them is purely cautionary and off by default.
    if include_untracked:
        cmd = "git ls-files --others --exclude-standard"
        rc, stdout, _ = run_cmd(cmd, repo_path)
        if rc == 0 and stdout.strip():
            for f in stdout.strip().split("\n"):
                if f:
                    cmd2 = f"grep -F '{username}' '{f}' 2>/dev/null"
                    rc2, out2, _ = run_cmd(cmd2, repo_path)
                    if rc2 == 0 and out2.strip():
                        for line in out2.strip().split("\n")[:3]:
                            findings.append(f"{f}: {line[:80]}")

    passed = len(findings) == 0
    return CheckResult("Local username", passed, findings[:10], info=f"checking for '{username}'")


def run_checks(repo_path: str, deep: bool = False,
               include_untracked: bool = False, **kwargs) -> List[CheckResult]:
    """Run all local username checks. Standard step interface."""
    return [check_local_username(repo_path, include_untracked=include_untracked)]

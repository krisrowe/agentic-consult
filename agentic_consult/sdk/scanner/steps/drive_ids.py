"""Google Drive/Doc/Sheet ID checks."""

from typing import List

from ..utils import CheckResult, run_cmd, DIFF_METADATA_FILTER


def check_drive_ids(repo_path: str) -> CheckResult:
    """Check for Google Drive/Doc/Sheet file IDs."""
    # Drive IDs are typically 33 or 44 characters, alphanumeric with - and _
    # Look for them in specific contexts to reduce false positives
    patterns = [
        r'/d/[A-Za-z0-9_-]{20,50}',  # Drive URL format
        r'id=[A-Za-z0-9_-]{20,50}',   # Query param format
        r'folders/[A-Za-z0-9_-]{20,50}',  # Folder URL
    ]

    findings = []
    for pattern in patterns:
        cmd = f"git diff --staged 2>/dev/null | {DIFF_METADATA_FILTER} | grep -oE '{pattern}' | head -10"
        rc, stdout, _ = run_cmd(cmd, repo_path)
        if stdout.strip():
            for match in stdout.strip().split("\n")[:3]:
                findings.append(match)

    passed = len(findings) == 0
    return CheckResult("Google Drive IDs", passed, findings[:10])


def run_checks(repo_path: str, deep: bool = False) -> List[CheckResult]:
    """Run all Drive ID checks. Standard step interface."""
    return [check_drive_ids(repo_path)]

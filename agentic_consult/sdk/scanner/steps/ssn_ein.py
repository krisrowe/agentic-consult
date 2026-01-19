"""SSN and EIN pattern checks."""

from typing import List

from ..utils import CheckResult, run_cmd, DIFF_METADATA_FILTER


def check_ssn_ein(repo_path: str) -> CheckResult:
    """Check for SSN (XXX-XX-XXXX) and EIN (XX-XXXXXXX) patterns."""
    findings = []

    # SSN pattern
    cmd = f"git diff --staged 2>/dev/null | {DIFF_METADATA_FILTER} | grep -oE '[0-9]{{3}}-[0-9]{{2}}-[0-9]{{4}}' | head -10"
    rc, stdout, _ = run_cmd(cmd, repo_path)
    if stdout.strip():
        for match in stdout.strip().split("\n"):
            # Exclude obvious non-SSN patterns like dates
            if not match.startswith("000") and not match.startswith("666"):
                findings.append(f"SSN-like: {match}")

    # EIN pattern
    cmd = f"git diff --staged 2>/dev/null | {DIFF_METADATA_FILTER} | grep -oE '[0-9]{{2}}-[0-9]{{7}}' | head -10"
    rc, stdout, _ = run_cmd(cmd, repo_path)
    if stdout.strip():
        for match in stdout.strip().split("\n"):
            findings.append(f"EIN-like: {match}")

    passed = len(findings) == 0
    return CheckResult("SSN/EIN patterns", passed, findings[:10])


def run_checks(repo_path: str, deep: bool = False) -> List[CheckResult]:
    """Run all SSN/EIN checks. Standard step interface."""
    return [check_ssn_ein(repo_path)]

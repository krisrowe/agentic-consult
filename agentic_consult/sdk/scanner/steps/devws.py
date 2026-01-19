"""External devws precommit check."""

from typing import List

from ..utils import CheckResult, run_cmd


def run_devws_precommit(repo_path: str) -> CheckResult:
    """Run devws precommit as external check."""
    rc, stdout, stderr = run_cmd("devws precommit 2>&1", repo_path)

    if rc == 0:
        return CheckResult("devws precommit", True)

    findings = []
    if "FOUND" in stdout:
        for line in stdout.split("\n"):
            line = line.strip()
            if line.startswith("[!]") or line.startswith("-"):
                findings.append(line[:100])

    if not findings:
        findings = ["devws precommit reported issues"]

    return CheckResult("devws precommit", False, findings[:10])


def run_checks(repo_path: str, deep: bool = False) -> List[CheckResult]:
    """Run devws precommit. Standard step interface."""
    return [run_devws_precommit(repo_path)]

"""Core scanner orchestration - coordinates all checks.

Scans uncommitted changes (anything that could get committed) by default.
Use deep=True to also scan full git history.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from .config import find_patterns_yaml
from .utils import CheckResult, run_cmd
from .steps import run_all_steps, get_step_names


class InvalidCheckModuleError(ValueError):
    """Raised when only_check specifies an unknown module."""
    pass


class MissingUserConfigError(Exception):
    """Raised when require_user_config=True and no config file found."""
    pass


@dataclass
class ScanReport:
    """Complete scan report with all check results."""
    repo_path: str
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(not c.passed and not c.skipped for c in self.checks)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed and not c.skipped)

    def summary(self) -> str:
        lines = [f"Scan: {self.repo_path}", f"Passed: {self.passed_count}, Failed: {self.failed_count}"]
        for c in self.checks:
            status = "PASS" if c.passed else ("SKIP" if c.skipped else "FAIL")
            lines.append(f"  [{status}] {c.name}")
            for f in c.findings[:5]:
                lines.append(f"    - {f}")
            if len(c.findings) > 5:
                lines.append(f"    ... and {len(c.findings) - 5} more")
        return "\n".join(lines)


def get_uncommitted_files(repo_path: str, include_untracked: bool = False) -> List[str]:
    """Get files relevant to a precommit check (staged + unstaged).

    Untracked files are not staged and won't be in the commit.  Scanning
    them is purely cautionary and off by default — opt in with
    ``include_untracked=True``.
    """
    rc, staged, _ = run_cmd("git diff --cached --name-only", repo_path)
    staged_files = staged.strip().split("\n") if staged.strip() else []

    rc, modified, _ = run_cmd("git diff --name-only", repo_path)
    modified_files = modified.strip().split("\n") if modified.strip() else []

    if include_untracked:
        rc, untracked, _ = run_cmd("git ls-files --others --exclude-standard", repo_path)
        untracked_files = untracked.strip().split("\n") if untracked.strip() else []
    else:
        untracked_files = []

    all_files = set(staged_files + modified_files + untracked_files)
    return [f for f in all_files if f]


def check_git_repo(repo_path: str) -> CheckResult:
    """Verify path is a git repository.

    Works for normal repos (.git/ directory) and bare repos where
    GIT_DIR is set in the environment (e.g., when running as a hook).
    """
    git_dir = Path(repo_path) / ".git"
    if git_dir.exists():
        return CheckResult("Git repository", True)
    # When git runs a hook, it sets GIT_DIR in the environment.
    # This supports bare repo setups (e.g., dotfiles managers).
    if os.environ.get("GIT_DIR"):
        return CheckResult("Git repository", True)
    return CheckResult("Git repository", False, ["Not a git repository"])


def run_scan(repo_path: str, deep: bool = False,
             on_check_complete: callable = None,
             only_check: str = None,
             require_user_config: bool = False,
             include_untracked: bool = False) -> ScanReport:
    """Run all checks on a repository.

    Args:
        repo_path: Path to git repository
        deep: If True, also scan full git history (slower)
        on_check_complete: Optional callback(check_result, current, total) called after each check
        only_check: If specified, run only this step's checks. Use get_step_names() for valid values.
        require_user_config: If True, raise MissingUserConfigError when no
                            sensitive-patterns.yaml config file is found
        include_untracked: If True, also scan untracked files (off by default)

    Returns:
        ScanReport with all check results

    Raises:
        InvalidCheckModuleError: If only_check is not a valid step name
        MissingUserConfigError: If require_user_config=True and no config found
    """
    valid_steps = set(get_step_names())

    if only_check is not None and only_check not in valid_steps:
        raise InvalidCheckModuleError(
            f"Invalid check module: '{only_check}'. "
            f"Valid modules: {sorted(valid_steps)}"
        )

    if require_user_config and find_patterns_yaml() is None:
        raise MissingUserConfigError(
            "User config required but sensitive-patterns.yaml not found"
        )

    report = ScanReport(repo_path=repo_path)

    # Pre-calculate total checks (git repo check + all step results)
    # Run steps to get results, then iterate with correct total
    step_results = run_all_steps(repo_path, deep=deep, only_step=only_check,
                                 include_untracked=include_untracked)
    total_checks = 1 + len(step_results)  # 1 for git repo check

    # Check it's a git repo first
    result = check_git_repo(repo_path)
    report.checks.append(result)
    if on_check_complete:
        on_check_complete(result, 1, total_checks)
    if not result.passed:
        return report

    # Add step results
    for i, result in enumerate(step_results, start=2):
        report.checks.append(result)
        if on_check_complete:
            on_check_complete(result, i, total_checks)

    return report

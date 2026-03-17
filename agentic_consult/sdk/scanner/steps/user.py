"""User-specific pattern checks from sensitive-patterns.yaml."""

from typing import List, Tuple

from ..utils import CheckResult, run_cmd, DIFF_METADATA_FILTER
from ..config import load_patterns, build_regex_for_pattern


def check_uncommitted_content(repo_path: str, simple_patterns: List[str],
                               special_patterns: List[Tuple[dict, str]],
                               include_untracked: bool = False) -> CheckResult:
    """Check uncommitted changes for sensitive patterns."""
    if not simple_patterns and not special_patterns:
        return CheckResult("Sensitive patterns in uncommitted", True, [], skipped=True)

    findings = []

    if simple_patterns:
        patterns = "|".join(simple_patterns)
        cmd = f"git diff --staged 2>/dev/null | {DIFF_METADATA_FILTER} | grep -iE '{patterns}' | head -20"
        rc, stdout, _ = run_cmd(cmd, repo_path)
        if stdout.strip():
            for line in stdout.strip().split("\n")[:5]:
                findings.append(f"[staged] {line[:80]}")

        cmd = f"git diff 2>/dev/null | {DIFF_METADATA_FILTER} | grep -iE '{patterns}' | head -20"
        rc, stdout, _ = run_cmd(cmd, repo_path)
        if stdout.strip():
            for line in stdout.strip().split("\n")[:5]:
                findings.append(f"[unstaged] {line[:80]}")

        # Untracked files aren't staged and won't be in the commit —
        # scanning them is purely cautionary and off by default.
        if include_untracked:
            cmd = f"git ls-files --others --exclude-standard | head -50 | xargs -I{{}} grep -liE '{patterns}' {{}} 2>/dev/null | head -10"
            rc, stdout, _ = run_cmd(cmd, repo_path)
            if stdout.strip():
                for f in stdout.strip().split("\n")[:5]:
                    findings.append(f"[untracked] {f}")

    passed = len(findings) == 0
    return CheckResult("Sensitive patterns in uncommitted", passed, findings)


def check_history(repo_path: str, simple_patterns: List[str],
                  special_patterns: List[Tuple[dict, str]]) -> CheckResult:
    """Check git history for sensitive patterns (deep mode)."""
    if not simple_patterns:
        return CheckResult("Sensitive patterns in history", True, [], skipped=True)

    patterns = "|".join(simple_patterns)
    cmd = f"git log -p --all 2>/dev/null | {DIFF_METADATA_FILTER} | grep -iE '{patterns}' | head -20"
    rc, stdout, _ = run_cmd(cmd, repo_path)

    findings = []
    if stdout.strip():
        for line in stdout.strip().split("\n")[:10]:
            findings.append(line[:80])

    passed = len(findings) == 0
    return CheckResult("Sensitive patterns in history", passed, findings)


def check_commits(repo_path: str, simple_patterns: List[str]) -> CheckResult:
    """Check commit messages for sensitive patterns."""
    if not simple_patterns:
        return CheckResult("Sensitive patterns in commits", True, [], skipped=True)

    patterns = "|".join(simple_patterns)
    cmd = f"git log --all --format='%s%n%b' 2>/dev/null | grep -iE '{patterns}' | head -10"
    rc, stdout, _ = run_cmd(cmd, repo_path)

    findings = []
    if stdout.strip():
        for line in stdout.strip().split("\n")[:5]:
            findings.append(line[:80])

    passed = len(findings) == 0
    return CheckResult("Sensitive patterns in commits", passed, findings)


def check_stash(repo_path: str) -> CheckResult:
    """Check for stash entries (should be cleared before commit)."""
    cmd = "git stash list 2>/dev/null | wc -l"
    rc, stdout, _ = run_cmd(cmd, repo_path)

    count = int(stdout.strip()) if stdout.strip().isdigit() else 0
    if count > 0:
        return CheckResult("Stash entries", False, [f"{count} stash entries exist (should be cleared)"])
    return CheckResult("Stash entries", True)


def check_reflog(repo_path: str, simple_patterns: List[str]) -> CheckResult:
    """Check reflog for sensitive patterns."""
    if not simple_patterns:
        return CheckResult("Reflog patterns", True, [], skipped=True)

    patterns = "|".join(simple_patterns[:5])
    cmd = f"git reflog 2>/dev/null | grep -iE '{patterns}' | head -5"
    rc, stdout, _ = run_cmd(cmd, repo_path)

    findings = []
    if stdout.strip():
        for line in stdout.strip().split("\n")[:3]:
            findings.append(line[:80])

    passed = len(findings) == 0
    return CheckResult("Reflog patterns", passed, findings)


def check_filenames(repo_path: str, simple_patterns: List[str], deep: bool = False) -> CheckResult:
    """Check filenames for sensitive patterns."""
    if not simple_patterns:
        return CheckResult("Sensitive filenames", True, [], skipped=True)

    findings = []
    patterns = "|".join(simple_patterns)

    cmd = f"git ls-files 2>/dev/null | grep -iE '{patterns}' | head -10"
    rc, stdout, _ = run_cmd(cmd, repo_path)
    if stdout.strip():
        for f in stdout.strip().split("\n")[:5]:
            findings.append(f"[current] {f}")

    if deep:
        cmd = f"git log --all --name-only --format='' 2>/dev/null | sort -u | grep -iE '{patterns}' | head -10"
        rc, stdout, _ = run_cmd(cmd, repo_path)
        if stdout.strip():
            for f in stdout.strip().split("\n")[:5]:
                findings.append(f"[history] {f}")

    passed = len(findings) == 0
    return CheckResult("Sensitive filenames", passed, findings)


def check_branches(repo_path: str, simple_patterns: List[str]) -> CheckResult:
    """Check branch names for sensitive patterns."""
    if not simple_patterns:
        return CheckResult("Branch names", True, [], skipped=True)

    patterns = "|".join(simple_patterns)
    cmd = f"git branch -a 2>/dev/null | grep -iE '{patterns}' | head -5"
    rc, stdout, _ = run_cmd(cmd, repo_path)

    findings = []
    if stdout.strip():
        for line in stdout.strip().split("\n")[:3]:
            findings.append(line.strip())

    passed = len(findings) == 0
    return CheckResult("Branch names", passed, findings)


def check_tags(repo_path: str, simple_patterns: List[str]) -> CheckResult:
    """Check tag names for sensitive patterns."""
    if not simple_patterns:
        return CheckResult("Tag names", True, [], skipped=True)

    patterns = "|".join(simple_patterns)
    cmd = f"git tag 2>/dev/null | grep -iE '{patterns}' | head -5"
    rc, stdout, _ = run_cmd(cmd, repo_path)

    findings = []
    if stdout.strip():
        for line in stdout.strip().split("\n")[:3]:
            findings.append(line.strip())

    passed = len(findings) == 0
    return CheckResult("Tag names", passed, findings)


def run_checks(repo_path: str, deep: bool = False,
               include_untracked: bool = False, **kwargs) -> List[CheckResult]:
    """Run all user pattern checks. Standard step interface."""
    patterns_config, simple_patterns = load_patterns()

    special_patterns = []
    for p in patterns_config:
        if p.get("word_boundary") or p.get("not_followed_by"):
            special_patterns.append((p, build_regex_for_pattern(p)))

    results = [
        check_uncommitted_content(repo_path, simple_patterns, special_patterns,
                                  include_untracked=include_untracked),
        check_filenames(repo_path, simple_patterns, deep=deep),
        check_branches(repo_path, simple_patterns),
        check_tags(repo_path, simple_patterns),
    ]

    if deep:
        results.extend([
            check_history(repo_path, simple_patterns, special_patterns),
            check_commits(repo_path, simple_patterns),
            check_stash(repo_path),
            check_reflog(repo_path, simple_patterns),
        ])

    return results

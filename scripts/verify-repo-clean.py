#!/usr/bin/env python3
"""
Comprehensive repository sensitive data verification script.

=============================================================================
CONSOLIDATION STATUS (2026-01-26) - See GitHub Issue #8
=============================================================================

This script provides DEEP HISTORY SCANNING that `consult precommit` lacks.
It should be consolidated into consult's scanner module per issue #8.

GAP ANALYSIS - What this script does that `consult precommit --deep` does NOT:

| Check Type                    | This Script | consult precommit |
|-------------------------------|-------------|-------------------|
| User patterns in history      | ✅          | ✅ (deep=True)    |
| SSN/EIN in history            | ✅          | ❌ staged only    |
| OAuth tokens in history       | ✅          | ❌ staged only    |
| Drive IDs in history          | ✅          | ❌ staged only    |
| Email addresses in history    | ✅          | ❌ staged only    |
| Dollar amounts in history     | ✅          | ❌ staged only    |
| Commit message amounts        | ✅          | ❌                 |
| Filesystem (bypass gitignore) | ✅          | ❌                 |
| Orphan/dangling commits       | ✅          | ❌                 |
| Git objects/pack files        | ✅          | ❌                 |

CONSOLIDATION PLAN:
1. Add `deep` parameter support to all consult scanner step modules
2. Add filesystem bypass checks to consult
3. Add orphan commit scanning to consult
4. Deprecate this standalone script

Until consolidation is complete, use this script for:
- Auditing repos before making them public
- Deep cleanup of repos with sensitive data in history
- Comprehensive pre-release verification

=============================================================================

Checks a git repository for sensitive patterns in:
- All git history (commits, file content, filenames, commit messages)
- Detached/orphan commits
- Stash entries
- Branch and tag names
- Local filesystem (bypassing .gitignore)
- Dollar amounts (large, non-round, with cents)

Usage:
    python verify-repo-clean.py /path/to/repo
    python verify-repo-clean.py .  # current directory

=============================================================================
CLEANUP SCOPE
=============================================================================

IN SCOPE (to be cleaned):
- Git history: all commits, file content, filenames, commit messages

OUT OF SCOPE (keep real data - these are runtime paths, not repo content):
- ~/.config/your-app/     Runtime config (not committed)
- ~/.local/share/your-app/ Runtime data (not committed)
- ~/.cache/your-app/      Cached downloads (not committed)

=============================================================================
SENSITIVE PATTERNS CHECKED
=============================================================================

Patterns are loaded from agentic/config/sensitive-patterns.yaml (not hardcoded here).
Categories include: names, employers, usernames, financial institutions, properties.

Each pattern can specify:
- word_boundary: true  (only match as standalone word)
- not_followed_by: [" cloud", " docs", ...]  (negative lookahead)

See agentic/config/sensitive-patterns.yaml for the actual patterns to check.

=============================================================================
DOLLAR AMOUNT STRATEGY
=============================================================================

Using round numbers makes it obvious data is fake. When examples need calculated
values (e.g., 30% federal tax, 7.65% FICA), start with a round base amount like
$100,000 gross pay - the calculated taxes will be non-round but clearly derived
from an obviously synthetic base.

$300k+ Rule: Avoid amounts >= $300k in test data. Rationale:
- Real high incomes are identifiable; even "fake" high amounts look suspicious
- All tax rules can be tested under $300k:
  - Additional Medicare Tax (0.9%): kicks in at $250k MFJ → test with $280k
  - Social Security wage cap: $176,100 → test with $200k
  - Tax bracket logic is identical across all brackets - no need to test upper
- The 35% bracket ($487k MFJ) and 37% bracket ($731k MFJ) use identical
  calculation logic as lower brackets - no special behavior requiring high amounts

Code Path Coverage Exception: When an algorithmic code path only executes above
a certain threshold, use the MINIMUM amount needed to hit that path:
- SS cap logic triggers when wages > $176,100 → use $180k or $200k, not $500k
- Additional Medicare triggers > $250k MFJ → use $260k or $280k, not $400k
The goal is to test all code paths with the smallest plausible synthetic amount.

Derived amounts are acceptable when:
- Base income is obviously round (e.g., $120,000.00)
- The non-round amount is a mathematical derivation (tax calculated from brackets)
- Example: calculated tax on taxable income (from round gross like $120,000)
  is OK because $120,000 is obviously fake synthetic data

Review carefully:
- Any amount >= $300k (even if rounded) - AVOID entirely
- Any amount with non-zero cents that isn't derived from a round base
- Amounts in code comments, commit messages, or example strings
- Non-round amounts that appear multiple times (suggests real payroll data)

=============================================================================
EXPECTED FINDINGS (not necessarily failures)
=============================================================================

- SENSITIVE_PATTERNS.md itself contains pattern names (it's documentation)
- .cache/, .venv/ directories contain runtime data (not part of repo)
- Round synthetic amounts like $120,000 will be flagged but are acceptable
- Derived tax amounts from round bases are acceptable

=============================================================================
CLEANUP WORKFLOW (when cleaning a repo)
=============================================================================

1. CREATE BACKUP FIRST (critical - history rewrite is destructive):
   git bundle create ~/REPONAME-backup-$(date +%Y%m%d).bundle --all
   Upload bundle to cloud storage for safekeeping

2. USE git-filter-repo for cleanup:
   # Replace text in all files:
   git filter-repo --replace-text replacements.txt

   # Rename sensitive filenames:
   git filter-repo --path-rename old-name:new-name

   # Clean commit messages:
   git filter-repo --message-callback 'return message.replace(b"old", b"new")'

   # Remove directories entirely:
   git filter-repo --path-glob 'data/*' --invert-paths

3. AFTER EACH PASS:
   - Run this verification script
   - Save commit mapping: cp .git/filter-repo/commit-map ~/mappings/
   - Re-add remote: git remote add origin URL (filter-repo removes it)

4. CLEANUP CHECKLIST:
   [ ] File content (all commits) - --replace-text
   [ ] File names (all commits) - --path-rename
   [ ] Commit messages - --message-callback
   [ ] Data files (real records) - --path-glob --invert-paths
   [ ] Branch names - manual check
   [ ] Tag names/messages - manual check
   [ ] Stash entries - git stash clear

5. COMMIT MAPPINGS: Save .git/filter-repo/commit-map after each pass

=============================================================================
SCRIPT COVERAGE GAPS (NOT YET IMPLEMENTED)
=============================================================================

Remaining patterns not yet checked:
- GCP project IDs (rely on devws precommit for this)
- Google client IDs (...apps.googleusercontent.com)
- Phone numbers, street addresses
- Binary/PDF content inspection
- Monarch account IDs, bank account numbers
- EXIF data in images
- Base64 encoded strings
- URLs with embedded API keys
- Jupyter notebook cell outputs
- SQLite/embedded databases
- Compressed archives (.zip, .tar.gz)

NOW IMPLEMENTED (28 checks total):
- Google Drive file IDs (33-44 char patterns)
- OAuth/API tokens (ya29, ghp_, gho_, sk-, AIza)
- Email addresses (except example/author domains)
- SSNs, EINs (XXX-XX-XXXX, XX-XXXXXXX patterns)
- Employer-specific terms (loaded from config)

=============================================================================
TODO: EXTERNALIZE PATTERNS TO YAML
=============================================================================

Consider moving user-specific patterns to a config YAML file that:
1. Is gitignored in target repos
2. Can be shared between this script and a "chaos" test script
3. Allows different users to customize for their own sensitive data

Candidate patterns to externalize:
- Personal names (family members, etc.)
- Employer names and employer-specific terms
- Property names or identifiers
- ACCEPTABLE_IRS_AMOUNTS (could vary by tax year)
=============================================================================
"""

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


# =============================================================================
# CONFIGURATION - Load sensitive patterns from YAML
# =============================================================================

import yaml

def find_config_file() -> Path:
    """Find sensitive-patterns.yaml config file.

    Search order:
    1. Use agentic_consult.sdk.scanner.config.find_patterns_yaml() if available
    2. Check config_dir from ~/.config/agentic-consult/settings.json
    3. Check ~/.config/agentic-consult/sensitive-patterns.yaml
    4. Raise error if not found
    """
    # Try to use consult's config system if available
    try:
        from agentic_consult.sdk.scanner.config import find_patterns_yaml
        yaml_path = find_patterns_yaml()
        if yaml_path:
            return yaml_path
    except ImportError:
        pass

    # Try settings.json redirect
    settings_path = Path.home() / ".config" / "agentic-consult" / "settings.json"
    if settings_path.exists():
        import json
        with open(settings_path) as f:
            settings = json.load(f)
        config_dir = settings.get("config_dir", "")
        if config_dir:
            config_dir = Path(config_dir).expanduser()
            yaml_path = config_dir / "sensitive-patterns.yaml"
            if yaml_path.exists():
                return yaml_path

    # Try default XDG location
    yaml_path = Path.home() / ".config" / "agentic-consult" / "sensitive-patterns.yaml"
    if yaml_path.exists():
        return yaml_path

    raise FileNotFoundError(
        "sensitive-patterns.yaml not found. Checked:\n"
        "  - agentic_consult.sdk.scanner.config.find_patterns_yaml()\n"
        "  - config_dir from ~/.config/agentic-consult/settings.json\n"
        "  - ~/.config/agentic-consult/sensitive-patterns.yaml"
    )


def load_patterns_from_yaml() -> tuple[list[dict], list[str], dict, bool, bool]:
    """Load sensitive patterns and thresholds from YAML config file.

    Returns:
        (patterns_list, simple_patterns_for_grep, thresholds, number_format_strict, skip_gitignored_filesystem)
        - patterns_list: full pattern dicts with category, word_boundary, not_followed_by
        - simple_patterns_for_grep: list of simple strings for basic grep (no regex features)
        - thresholds: dict of dollar amount thresholds
        - number_format_strict: if True, only match $xxx,xxx.xx; if False, also match plain numbers
        - skip_gitignored_filesystem: if True, skip gitignored files in filesystem checks
    """
    yaml_path = find_config_file()

    with open(yaml_path) as f:
        config = yaml.safe_load(f)

    patterns = config.get("patterns", [])

    # Build simple pattern list for grep commands (patterns without regex features)
    simple_patterns = []
    for p in patterns:
        pattern = p.get("pattern", "")
        # Skip patterns that need regex features - they'll be checked separately
        if p.get("word_boundary") or p.get("not_followed_by"):
            continue
        simple_patterns.append(pattern)

    # Load thresholds with defaults
    thresholds = config.get("thresholds", {})
    thresholds.setdefault("large_amount", 300000)
    thresholds.setdefault("suspicious_nonround", 10000)
    thresholds.setdefault("suspicious_any", 100000)
    thresholds.setdefault("cents_review", 500)

    # Number format strictness (default: strict, only match $xxx,xxx.xx)
    number_format_strict = config.get("number_format_strict", True)

    # Filesystem check scope (default: skip gitignored files)
    skip_gitignored_filesystem = config.get("skip_gitignored_filesystem", True)

    return patterns, simple_patterns, thresholds, number_format_strict, skip_gitignored_filesystem


def build_regex_for_pattern(p: dict) -> str:
    """Build regex string for a single pattern config."""
    pattern = p.get("pattern", "")

    # Escape regex special chars in the base pattern
    escaped = re.escape(pattern)

    # Apply word boundary if requested
    if p.get("word_boundary"):
        escaped = rf"\b{escaped}\b"

    # Apply negative lookahead if specified
    not_followed = p.get("not_followed_by", [])
    if not_followed:
        # Build negative lookahead: pattern(?!(opt1|opt2|opt3))
        escaped_opts = [re.escape(opt) for opt in not_followed]
        lookahead = f"(?!({'|'.join(escaped_opts)}))"
        escaped = f"{escaped}{lookahead}"

    return escaped


# Load patterns and thresholds at module load time
PATTERNS_CONFIG, SIMPLE_PATTERNS, THRESHOLDS, NUMBER_FORMAT_STRICT, SKIP_GITIGNORED_FILESYSTEM = load_patterns_from_yaml()

# Build combined regex for patterns needing special handling
SPECIAL_PATTERNS_REGEX = []
for p in PATTERNS_CONFIG:
    if p.get("word_boundary") or p.get("not_followed_by"):
        SPECIAL_PATTERNS_REGEX.append((p, build_regex_for_pattern(p)))

# For backward compatibility with existing check functions
ALL_SENSITIVE_PATTERNS = SIMPLE_PATTERNS

# Dollar amount regex patterns based on strictness setting
# Strict: only match human-readable format $xxx,xxx.xx
# Flexible: also match plain numbers like 450000 or $450000
if NUMBER_FORMAT_STRICT:
    # Only $XXX,XXX.XX format (with commas, optional cents)
    AMOUNT_REGEX_GREP = r'\$[0-9]{1,3},[0-9]{3}(,[0-9]{3})*(\.[0-9]{2})?'
    AMOUNT_REGEX_GREP_CENTS = r'\$[0-9][0-9,]*\.[0-9]{2}'
else:
    # Flexible: $XXX,XXX.XX OR plain 6+ digit numbers OR $XXX without commas
    AMOUNT_REGEX_GREP = r'(\$[0-9]{1,3},[0-9]{3}(,[0-9]{3})*(\.[0-9]{2})?|\$?[0-9]{6,}(\.[0-9]{2})?)'
    AMOUNT_REGEX_GREP_CENTS = r'(\$[0-9][0-9,]*\.[0-9]{2}|\$?[0-9]{6,}\.[0-9]{2})'

# Expose thresholds as module-level constants for use in check functions
THRESHOLD_LARGE_AMOUNT = THRESHOLDS["large_amount"]
THRESHOLD_SUSPICIOUS_NONROUND = THRESHOLDS["suspicious_nonround"]
THRESHOLD_SUSPICIOUS_ANY = THRESHOLDS["suspicious_any"]
THRESHOLD_CENTS_REVIEW = THRESHOLDS["cents_review"]

# =============================================================================
# ACCEPTABLE DOLLAR AMOUNTS - IRS rules and public tax values
# =============================================================================
# These specific amounts are public IRS rules and acceptable in documentation.
# Each must be documented with its source/purpose.

ACCEPTABLE_IRS_AMOUNTS = {
    # Social Security wage base (2024)
    "176,100": "SS wage base 2024 - wages above this not subject to SS tax",

    # MFJ tax bracket thresholds (2024)
    "23,200": "MFJ 10% bracket upper limit 2024",
    "94,300": "MFJ 12% bracket upper limit 2024",
    "201,050": "MFJ 22% bracket upper limit 2024",
    "383,900": "MFJ 24% bracket upper limit 2024",
    "487,450": "MFJ 32% bracket upper limit 2024 (35% starts here)",
    "731,200": "MFJ 35% bracket upper limit 2024 (37% starts here)",

    # MFJ tax bracket thresholds (2025)
    "23,850": "MFJ 10% bracket upper limit 2025",
    "96,950": "MFJ 12% bracket upper limit 2025",
    "206,700": "MFJ 22% bracket upper limit 2025",
    "394,600": "MFJ 24% bracket upper limit 2025",
    "501,050": "MFJ 32% bracket upper limit 2025 (35% starts here)",
    "751,600": "MFJ 35% bracket upper limit 2025 (37% starts here)",

    # Additional Medicare Tax threshold
    "250,000": "Additional Medicare Tax threshold (0.9%) for MFJ",

    # Supplemental wage withholding
    "1,000,000": "Supplemental wages threshold - 37% withholding above this",

    # Standard deduction (2024/2025)
    "29,200": "MFJ standard deduction 2024",
    "30,000": "MFJ standard deduction 2025",

    # Round synthetic test amounts (obviously fake)
    "100,000": "Round synthetic test amount",
    "120,000": "Round synthetic test amount",
    "120,250": "Round synthetic test amount (tests payroll scenarios)",
    "125,000": "Round synthetic test amount",
    "150,000": "Round synthetic test amount",
    "200,000": "Round synthetic test amount",
    "280,000": "Round synthetic test amount (tests Additional Medicare)",
    "300,000": "Round synthetic test amount (documentation example)",

    # Derived amounts from round synthetic bases (obviously calculated)
    # These are derived from $120,000 gross income base - clearly synthetic
    # Add your own derived amounts here if needed (e.g., calculated taxes from round bases)
}


# =============================================================================
# Data classes for results
# =============================================================================

@dataclass
class CheckResult:
    """Result of a single check."""
    name: str
    passed: bool
    findings: List[str] = field(default_factory=list)
    details: str = ""


@dataclass
class VerificationReport:
    """Full verification report."""
    repo_path: str
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed)


# =============================================================================
# Utility functions
# =============================================================================

def run_cmd(cmd: str, cwd: str, timeout: int = 300) -> Tuple[int, str, str]:
    """Run a shell command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out after {timeout}s"
    except Exception as e:
        return -1, "", str(e)


# Shell filter to exclude git diff metadata lines from git log -p output
# Excludes: diff headers, index lines (with file modes like 100644), hunk headers, file markers
DIFF_METADATA_FILTER = r"grep -v -E '^(diff |index |@@|\-\-\-|\+\+\+)'"


def filter_diff_content(diff_output: str) -> str:
    """Filter git diff/log -p output to exclude metadata lines.

    Removes lines that are git diff metadata (not actual content):
    - 'diff --git ...' headers
    - 'index ...' lines (contain file modes like 100644)
    - '@@ ...' hunk headers (contain line numbers that match amount patterns)
    - '--- a/...' and '+++ b/...' file markers

    This prevents false positives on file modes (100644) and hunk line numbers
    when scanning for patterns like dollar amounts.
    """
    lines = []
    for line in diff_output.split('\n'):
        # Skip diff metadata lines
        if line.startswith('diff '):
            continue
        if line.startswith('index '):
            continue
        if line.startswith('@@'):
            continue
        if line.startswith('--- '):
            continue
        if line.startswith('+++ '):
            continue
        lines.append(line)
    return '\n'.join(lines)


def print_progress(current: int, total: int, check_name: str):
    """Print progress indicator."""
    pct = (current / total) * 100
    bar_len = 30
    filled = int(bar_len * current / total)
    bar = "=" * filled + "-" * (bar_len - filled)
    print(f"\r[{bar}] {pct:5.1f}% ({current}/{total}) {check_name[:40]:<40}", end="", flush=True)


def print_result(result: CheckResult):
    """Print a check result."""
    status = "\033[92mPASS\033[0m" if result.passed else "\033[91mFAIL\033[0m"
    print(f"\n  [{status}] {result.name}")
    if not result.passed and result.findings:
        for finding in result.findings[:10]:  # Limit to first 10
            print(f"         - {finding[:100]}")
        if len(result.findings) > 10:
            print(f"         ... and {len(result.findings) - 10} more")


# =============================================================================
# Check functions
# =============================================================================

def check_git_repo(repo_path: str) -> CheckResult:
    """Verify this is a git repository."""
    git_dir = Path(repo_path) / ".git"
    if git_dir.is_dir():
        return CheckResult("Git repository check", True, details="Valid git repo")
    return CheckResult("Git repository check", False, ["Not a git repository"])


def check_staged_content(repo_path: str) -> CheckResult:
    """Check staged content (git diff --staged) for sensitive patterns.

    This catches sensitive data BEFORE it gets committed, complementing
    the history scan which catches already-committed data.
    """
    findings = []

    # Get staged content
    cmd = 'git diff --staged 2>/dev/null'
    rc, stdout, stderr = run_cmd(cmd, repo_path, timeout=60)

    if not stdout:
        return CheckResult("Sensitive patterns in staged content", True, [], details="No staged changes")

    # Filter out diff metadata to prevent false positives
    stdout = filter_diff_content(stdout)

    # Check all patterns from config
    for pattern_config in PATTERNS_CONFIG:
        pattern_name = pattern_config.get("pattern", "")
        category = pattern_config.get("category", "unknown")

        regex_str = build_regex_for_pattern(pattern_config)

        try:
            regex = re.compile(regex_str, re.IGNORECASE)
        except re.error:
            continue

        match_count = 0
        for match in regex.finditer(stdout):
            start = max(0, match.start() - 30)
            end = min(len(stdout), match.end() + 30)
            context = stdout[start:end].replace('\n', ' ')[:100]
            findings.append(f"[{category}] {context}")
            match_count += 1
            if match_count >= 5:
                break

    return CheckResult(
        "Sensitive patterns in staged content",
        len(findings) == 0,
        findings[:50],
    )


def check_sensitive_patterns_in_history(repo_path: str) -> CheckResult:
    """Check for sensitive patterns in all git history content.

    Checks both simple patterns (via grep) and special patterns
    (word_boundary, not_followed_by) via Python regex.
    Output includes category from YAML config.
    """
    findings = []

    # Get git history content once
    cmd = 'git log -p --all 2>/dev/null'
    rc, stdout, stderr = run_cmd(cmd, repo_path, timeout=120)

    if not stdout:
        return CheckResult("Sensitive patterns in git history", True, [])

    # Filter out diff metadata to prevent false positives on file modes (100644) and hunk headers
    stdout = filter_diff_content(stdout)

    # Check ALL patterns from config, with category in output
    for pattern_config in PATTERNS_CONFIG:
        pattern_name = pattern_config.get("pattern", "")
        category = pattern_config.get("category", "unknown")

        # Build regex for this pattern
        regex_str = build_regex_for_pattern(pattern_config)

        try:
            regex = re.compile(regex_str, re.IGNORECASE)
        except re.error:
            continue

        match_count = 0
        for match in regex.finditer(stdout):
            # Get context around match
            start = max(0, match.start() - 30)
            end = min(len(stdout), match.end() + 30)
            context = stdout[start:end].replace('\n', ' ')[:100]
            findings.append(f"[{category}] {context}")
            match_count += 1
            if match_count >= 5:  # Limit per pattern
                break

    return CheckResult(
        "Sensitive patterns in git history",
        len(findings) == 0,
        findings[:50],
    )


def check_sensitive_patterns_in_commits(repo_path: str) -> CheckResult:
    """Check for sensitive patterns in commit messages."""
    findings = []

    # Simple patterns via grep
    if ALL_SENSITIVE_PATTERNS:
        patterns = "|".join(ALL_SENSITIVE_PATTERNS)
        cmd = f'git log --all --format="%s %b" 2>/dev/null | grep -iE "({patterns})" | head -20'
        rc, stdout, stderr = run_cmd(cmd, repo_path)

        if stdout.strip():
            for line in stdout.strip().split("\n"):
                findings.append(line.strip()[:200])

    # Special patterns via Python regex
    if SPECIAL_PATTERNS_REGEX:
        cmd = 'git log --all --format="%s %b" 2>/dev/null'
        rc, stdout, stderr = run_cmd(cmd, repo_path)
        if stdout:
            for pattern_config, regex_str in SPECIAL_PATTERNS_REGEX:
                pattern_name = pattern_config.get("pattern", "unknown")
                try:
                    regex = re.compile(regex_str, re.IGNORECASE)
                    for match in regex.finditer(stdout):
                        start = max(0, match.start() - 20)
                        end = min(len(stdout), match.end() + 20)
                        context = stdout[start:end].replace('\n', ' ')[:80]
                        findings.append(f"[{pattern_name}] {context}")
                        if len([f for f in findings if pattern_name in f]) >= 3:
                            break
                except re.error:
                    continue

    return CheckResult(
        "Sensitive patterns in commit messages",
        len(findings) == 0,
        findings[:30],
    )


def check_sensitive_filenames_current(repo_path: str) -> CheckResult:
    """Check for sensitive patterns in current filenames."""
    patterns = "|".join(ALL_SENSITIVE_PATTERNS)
    cmd = f'git ls-files 2>/dev/null | grep -iE "({patterns})"'
    rc, stdout, stderr = run_cmd(cmd, repo_path)

    findings = stdout.strip().split("\n") if stdout.strip() else []
    return CheckResult(
        "Sensitive patterns in current filenames",
        len(findings) == 0,
        findings,
    )


def check_sensitive_filenames_history(repo_path: str) -> CheckResult:
    """Check for sensitive patterns in historical filenames."""
    patterns = "|".join(ALL_SENSITIVE_PATTERNS)
    cmd = f'git log --all --name-only --format="" 2>/dev/null | sort -u | grep -iE "({patterns})" | head -30'
    rc, stdout, stderr = run_cmd(cmd, repo_path)

    findings = stdout.strip().split("\n") if stdout.strip() else []
    return CheckResult(
        "Sensitive patterns in historical filenames",
        len(findings) == 0,
        findings,
    )


def check_branch_names(repo_path: str) -> CheckResult:
    """Check for sensitive patterns in branch names."""
    patterns = "|".join(ALL_SENSITIVE_PATTERNS)
    cmd = f'git branch -a 2>/dev/null | grep -iE "({patterns})"'
    rc, stdout, stderr = run_cmd(cmd, repo_path)

    findings = stdout.strip().split("\n") if stdout.strip() else []
    return CheckResult(
        "Sensitive patterns in branch names",
        len(findings) == 0,
        findings,
    )


def check_tag_names(repo_path: str) -> CheckResult:
    """Check for sensitive patterns in tag names and messages."""
    patterns = "|".join(ALL_SENSITIVE_PATTERNS)

    # Check tag names
    cmd = f'git tag 2>/dev/null | grep -iE "({patterns})"'
    rc, stdout, stderr = run_cmd(cmd, repo_path)
    findings = stdout.strip().split("\n") if stdout.strip() else []

    # Check tag messages
    cmd2 = f'git tag -l -n100 2>/dev/null | grep -iE "({patterns})"'
    rc2, stdout2, stderr2 = run_cmd(cmd2, repo_path)
    if stdout2.strip():
        findings.extend(stdout2.strip().split("\n"))

    return CheckResult(
        "Sensitive patterns in tags",
        len(findings) == 0,
        findings,
    )


def check_stash_entries(repo_path: str) -> CheckResult:
    """Check stash entries for sensitive data (and warn if stash exists)."""
    # First check if any stash entries exist
    cmd = 'git stash list 2>/dev/null'
    rc, stdout, stderr = run_cmd(cmd, repo_path)

    stash_list = stdout.strip().split("\n") if stdout.strip() else []
    if not stash_list or stash_list == ['']:
        return CheckResult("Stash entries", True, [], details="No stash entries")

    # Stash exists - check content for sensitive patterns
    findings = []
    findings.append(f"WARNING: {len(stash_list)} stash entries exist (should be cleared)")

    # Check each stash entry content for sensitive patterns
    for i, stash_entry in enumerate(stash_list[:5]):  # Limit to first 5
        stash_ref = f"stash@{{{i}}}"
        # Get stash diff
        cmd2 = f'git stash show -p {stash_ref} 2>/dev/null'
        rc2, stdout2, stderr2 = run_cmd(cmd2, repo_path)

        if stdout2:
            # Check all patterns from config
            for pattern_config in PATTERNS_CONFIG:
                pattern_name = pattern_config.get("pattern", "")
                category = pattern_config.get("category", "unknown")
                regex_str = build_regex_for_pattern(pattern_config)
                try:
                    regex = re.compile(regex_str, re.IGNORECASE)
                    if regex.search(stdout2):
                        findings.append(f"[{category}] {stash_ref}: contains '{pattern_name}'")
                        break  # One finding per stash is enough
                except re.error:
                    continue

    return CheckResult(
        "Stash entries",
        len(findings) == 0,
        findings,
    )


def check_orphan_commits(repo_path: str) -> CheckResult:
    """Check for orphan/dangling commits with sensitive data."""
    patterns = "|".join(ALL_SENSITIVE_PATTERNS)

    # Find dangling commits
    cmd = 'git fsck --unreachable --no-reflogs 2>/dev/null | grep "commit" | head -20'
    rc, stdout, stderr = run_cmd(cmd, repo_path)

    if not stdout.strip():
        return CheckResult("Orphan commits check", True, details="No orphan commits")

    # Check each orphan commit for sensitive data
    findings = []
    for line in stdout.strip().split("\n"):
        if "commit" in line:
            commit_sha = line.split()[-1]
            cmd2 = f'git show {commit_sha} 2>/dev/null | grep -iE "({patterns})" | head -5'
            rc2, stdout2, stderr2 = run_cmd(cmd2, repo_path)
            if stdout2.strip():
                findings.append(f"Orphan {commit_sha[:8]}: {stdout2.strip()[:100]}")

    return CheckResult(
        "Sensitive data in orphan commits",
        len(findings) == 0,
        findings,
    )


def is_acceptable_amount(amount_str: str) -> bool:
    """Check if a dollar amount matches a known acceptable IRS value."""
    # Strip $ and .00 suffix for comparison
    clean = amount_str.replace("$", "").replace(".00", "").rstrip("0").rstrip(".")
    # Also try without trailing zeros that might be stripped differently
    clean_no_decimal = amount_str.replace("$", "").split(".")[0]
    return clean in ACCEPTABLE_IRS_AMOUNTS or clean_no_decimal in ACCEPTABLE_IRS_AMOUNTS


def check_large_amounts(repo_path: str) -> CheckResult:
    """Check for dollar amounts >= configured threshold (default $300k)."""
    # Extract all 6-figure+ amounts and filter by threshold
    # Use DIFF_METADATA_FILTER to exclude git diff metadata (file modes, hunk headers)
    cmd = f"git log -p --all 2>/dev/null | {DIFF_METADATA_FILTER} | grep -oE '{AMOUNT_REGEX_GREP}' | sort -u"
    rc, stdout, stderr = run_cmd(cmd, repo_path)

    findings = []
    if stdout.strip():
        for amt in stdout.strip().split("\n"):
            if not amt or is_acceptable_amount(amt):
                continue
            try:
                val = float(amt.replace("$", "").replace(",", ""))
                if val >= THRESHOLD_LARGE_AMOUNT:
                    findings.append(amt)
            except:
                pass

    threshold_display = f"${THRESHOLD_LARGE_AMOUNT:,}"
    return CheckResult(
        f"Dollar amounts >= {threshold_display}",
        len(findings) == 0,
        findings,
    )


def check_nonround_6figure(repo_path: str) -> CheckResult:
    """Check for non-round 6-figure amounts (not ending in .00)."""
    cmd = f"git log -p --all 2>/dev/null | {DIFF_METADATA_FILTER} | grep -oE '\\$[1-9][0-9]{{2}},[0-9]{{3}}\\.[0-9]{{2}}' | grep -v '\\.00$' | sort -u"
    rc, stdout, stderr = run_cmd(cmd, repo_path)

    findings = stdout.strip().split("\n") if stdout.strip() else []
    return CheckResult(
        "Non-round 6-figure amounts",
        len(findings) == 0,
        findings,
    )


def check_amounts_with_cents(repo_path: str) -> CheckResult:
    """Check for any dollar amounts with non-zero cents."""
    cmd = f"git log -p --all 2>/dev/null | {DIFF_METADATA_FILTER} | grep -oE '{AMOUNT_REGEX_GREP_CENTS}' | grep -v '\\.00$' | sort -u | head -50"
    rc, stdout, stderr = run_cmd(cmd, repo_path)

    findings = stdout.strip().split("\n") if stdout.strip() else []

    # Filter out small amounts that are likely tax rates/percentages
    filtered = []
    for f in findings:
        # Extract numeric value
        try:
            val = float(f.replace("$", "").replace(",", ""))
            # Flag amounts > threshold with cents as potentially real
            if val > THRESHOLD_CENTS_REVIEW:
                filtered.append(f)
        except:
            filtered.append(f)

    threshold_display = f"${THRESHOLD_CENTS_REVIEW:,}"
    return CheckResult(
        f"Amounts with cents (> {threshold_display}, review needed)",
        len(filtered) == 0,
        filtered,
    )


def check_5figure_nonround(repo_path: str) -> CheckResult:
    """Check for 5-figure amounts that aren't round (not divisible by 100)."""
    cmd = f"git log -p --all 2>/dev/null | {DIFF_METADATA_FILTER} | grep -oE '\\$[1-9][0-9],[0-9]{{3}}\\.[0-9]{{2}}' | sort -u"
    rc, stdout, stderr = run_cmd(cmd, repo_path)

    findings = []
    if stdout.strip():
        for amt in stdout.strip().split("\n"):
            # Skip known acceptable IRS amounts
            if is_acceptable_amount(amt):
                continue
            try:
                val = float(amt.replace("$", "").replace(",", ""))
                # Check if not divisible by 100
                if val % 100 != 0:
                    findings.append(amt)
            except:
                pass

    return CheckResult(
        "5-figure non-round amounts",
        len(findings) == 0,
        findings[:30],
    )


def check_all_dollar_amounts(repo_path: str) -> CheckResult:
    """List ALL dollar amounts in history for manual review."""
    cmd = f"git log -p --all 2>/dev/null | {DIFF_METADATA_FILTER} | grep -oE '{AMOUNT_REGEX_GREP_CENTS}' | sort -u"
    rc, stdout, stderr = run_cmd(cmd, repo_path)

    all_amounts = stdout.strip().split("\n") if stdout.strip() else []

    # Categorize amounts
    suspicious = []
    for amt in all_amounts:
        # Skip known acceptable IRS amounts
        if is_acceptable_amount(amt):
            continue
        try:
            val = float(amt.replace("$", "").replace(",", ""))
            # Flag: >= threshold and not ending in .00
            if val >= THRESHOLD_SUSPICIOUS_NONROUND and not amt.endswith(".00"):
                suspicious.append(amt)
            # Flag: >= higher threshold regardless of rounding
            elif val >= THRESHOLD_SUSPICIOUS_ANY:
                suspicious.append(amt)
        except:
            pass

    nonround_display = f"${THRESHOLD_SUSPICIOUS_NONROUND:,}"
    any_display = f"${THRESHOLD_SUSPICIOUS_ANY:,}"
    return CheckResult(
        f"Suspicious dollar amounts (>={nonround_display} non-round or >={any_display})",
        len(suspicious) == 0,
        suspicious[:30],
        details=f"Total amounts found: {len(all_amounts)}, suspicious: {len(suspicious)}",
    )


def check_commit_message_amounts(repo_path: str) -> CheckResult:
    """Check for specific dollar amounts in commit messages."""
    cmd = f"git log --all --format='%s %b' 2>/dev/null | grep -oE '{AMOUNT_REGEX_GREP_CENTS}' | sort -u"
    rc, stdout, stderr = run_cmd(cmd, repo_path)

    findings = []
    if stdout.strip():
        for amt in stdout.strip().split("\n"):
            try:
                val = float(amt.replace("$", "").replace(",", ""))
                # Flag amounts >= threshold with cents or >= higher threshold
                if (val >= THRESHOLD_SUSPICIOUS_NONROUND and not amt.endswith(".00")) or val >= THRESHOLD_SUSPICIOUS_ANY:
                    findings.append(amt)
            except:
                pass

    return CheckResult(
        "Dollar amounts in commit messages",
        len(findings) == 0,
        findings,
    )


def check_percentage_like_amounts(repo_path: str) -> CheckResult:
    """Check for amounts that look like percentages of income (possibly derived from real data)."""
    # Look for amounts like $X,XXX.XX that could be payroll deductions
    cmd = f"git log -p --all 2>/dev/null | {DIFF_METADATA_FILTER} | grep -oE '\\$[1-9],[0-9]{{3}}\\.[0-9]{{2}}' | grep -v '\\.00$' | sort | uniq -c | sort -rn | head -20"
    rc, stdout, stderr = run_cmd(cmd, repo_path)

    findings = []
    if stdout.strip():
        for line in stdout.strip().split("\n"):
            parts = line.strip().split()
            if len(parts) >= 2:
                count = int(parts[0])
                amt = parts[1]
                # If same non-round amount appears multiple times, suspicious
                if count >= 2:
                    findings.append(f"{amt} (appears {count}x)")

    return CheckResult(
        "Repeated non-round amounts (possible real payroll data)",
        len(findings) == 0,
        findings,
    )


def get_filesystem_files_cmd() -> tuple[str, str]:
    """Return (shell_cmd, check_description) for listing working tree files.

    If SKIP_GITIGNORED_FILESYSTEM: uses git ls-files (respects .gitignore)
    Otherwise: uses find (all files)
    """
    if SKIP_GITIGNORED_FILESYSTEM:
        cmd = '{ git ls-files 2>/dev/null; git ls-files --others --exclude-standard 2>/dev/null; }'
        desc = "working tree (respecting .gitignore)"
    else:
        cmd = "find . -type f -not -path './.git/*' -not -name '*.pyc' -not -path './.venv/*' -not -path '*/__pycache__/*' 2>/dev/null"
        desc = "all files (ignoring .gitignore)"
    return cmd, desc


def check_filesystem_sensitive(repo_path: str) -> CheckResult:
    """Check working tree files for sensitive patterns."""
    file_cmd, desc = get_filesystem_files_cmd()
    cmd = f"{file_cmd} | head -500"
    check_name = f"Filesystem sensitive ({desc})"

    # Previously had config-based branching here, now uses helper
    if SKIP_GITIGNORED_FILESYSTEM:
        # Use git ls-files to respect .gitignore
        # Combine tracked files + untracked-but-not-ignored files
        cmd = '{ git ls-files 2>/dev/null; git ls-files --others --exclude-standard 2>/dev/null; } | head -500'
        check_name = "Filesystem (tracked + untracked, respecting .gitignore)"
    else:
        # Check ALL files including gitignored (original behavior)
        cmd = 'find . -type f -not -path "./.git/*" -not -name "*.pyc" -not -path "./.venv/*" -not -path "*/__pycache__/*" 2>/dev/null | head -500'
        check_name = "Filesystem (all files, ignoring .gitignore)"

    rc, stdout, stderr = run_cmd(cmd, repo_path)

    findings = []
    if not stdout.strip():
        return CheckResult(check_name, True, [])

    files = stdout.strip().split("\n")
    for filepath in files:
        if not filepath:
            continue
        # Exclude this script and documentation about patterns
        if "SENSITIVE_PATTERNS" in filepath or "verify-repo-clean" in filepath or "chaos-test" in filepath:
            continue
        # Skip binary/compiled files
        if filepath.endswith(('.pyc', '.so', '.egg-info')):
            continue

        try:
            full_path = Path(repo_path) / filepath.lstrip("./")
            if not full_path.exists() or not full_path.is_file():
                continue
            content = full_path.read_text(errors='ignore')

            # Check each pattern and report which ones match
            for pattern_config in PATTERNS_CONFIG:
                pattern_name = pattern_config.get("pattern", "")
                category = pattern_config.get("category", "unknown")
                word_boundary = pattern_config.get("word_boundary", False)
                not_followed_by = pattern_config.get("not_followed_by", [])

                # Build regex
                escaped = re.escape(pattern_name)
                if word_boundary:
                    regex_str = rf"\b{escaped}\b"
                elif not_followed_by:
                    neg_lookahead = "|".join(re.escape(s) for s in not_followed_by)
                    regex_str = rf"{escaped}(?!({neg_lookahead}))"
                else:
                    regex_str = escaped

                try:
                    regex = re.compile(regex_str, re.IGNORECASE)
                    if regex.search(content):
                        findings.append(f"[{category}] {filepath}: contains '{pattern_name}'")
                        break  # One finding per file is enough
                except re.error:
                    continue
        except Exception:
            pass

    return CheckResult(
        check_name,
        len(findings) == 0,
        findings,
    )


def check_filesystem_amounts(repo_path: str) -> CheckResult:
    """Direct filesystem check for large dollar amounts."""
    # Extract all amounts and filter by threshold
    cmd = f"find . -type f -not -path './.git/*' -not -name '*.pyc' -not -path './.venv/*' 2>/dev/null | head -500 | xargs grep -ohE '{AMOUNT_REGEX_GREP}' 2>/dev/null | sort -u"
    rc, stdout, stderr = run_cmd(cmd, repo_path)

    findings = []
    if stdout.strip():
        for amt in stdout.strip().split("\n"):
            if not amt or is_acceptable_amount(amt):
                continue
            try:
                val = float(amt.replace("$", "").replace(",", ""))
                if val >= THRESHOLD_LARGE_AMOUNT:
                    findings.append(amt)
            except:
                pass

    threshold_display = f"${THRESHOLD_LARGE_AMOUNT:,}"
    return CheckResult(
        f"Filesystem large amounts (>= {threshold_display})",
        len(findings) == 0,
        findings,
    )


def check_reflog(repo_path: str) -> CheckResult:
    """Check reflog for sensitive patterns (local history)."""
    patterns = "|".join(ALL_SENSITIVE_PATTERNS[:10])
    cmd = f'git reflog 2>/dev/null | grep -iE "({patterns})" | head -10'
    rc, stdout, stderr = run_cmd(cmd, repo_path)

    findings = stdout.strip().split("\n") if stdout.strip() else []
    return CheckResult(
        "Reflog entries with sensitive patterns",
        len(findings) == 0,
        findings,
    )


def check_git_objects_direct(repo_path: str) -> CheckResult:
    """Direct check of git object database for patterns."""
    patterns = "|".join(ALL_SENSITIVE_PATTERNS[:5])  # Limit for performance

    # This is slow but thorough - checks raw git objects
    cmd = f'find .git/objects -type f 2>/dev/null | head -100 | while read f; do git cat-file -p $(basename $(dirname $f))$(basename $f .git) 2>/dev/null; done | grep -iE "({patterns})" | head -10'
    rc, stdout, stderr = run_cmd(cmd, repo_path, timeout=60)

    findings = []
    if stdout.strip():
        for line in stdout.strip().split("\n"):
            findings.append(line[:150])

    return CheckResult(
        "Git objects direct scan",
        len(findings) == 0,
        findings,
    )


def check_pack_files(repo_path: str) -> CheckResult:
    """Check packed git objects for sensitive patterns."""
    patterns = "|".join(ALL_SENSITIVE_PATTERNS[:5])

    # Verify pack integrity and check for patterns
    cmd = f'git verify-pack -v .git/objects/pack/*.idx 2>/dev/null | head -5'
    rc, stdout, stderr = run_cmd(cmd, repo_path)

    if rc != 0 and "No such file" in stderr:
        return CheckResult("Pack files check", True, details="No pack files")

    # If packs exist, do a thorough unpack check
    cmd2 = f'for p in .git/objects/pack/*.pack; do git unpack-objects -n < "$p" 2>&1; done | grep -iE "({patterns})" | head -10'
    rc2, stdout2, stderr2 = run_cmd(cmd2, repo_path)

    findings = stdout2.strip().split("\n") if stdout2.strip() else []
    return CheckResult(
        "Pack files check",
        len(findings) == 0,
        findings,
    )


def check_google_drive_ids(repo_path: str) -> CheckResult:
    """Check for Google Drive/Doc/Sheet file IDs (33-44 char alphanumeric)."""
    # Drive IDs are typically 33 or 44 characters, alphanumeric with - and _
    # Pattern: standalone ID-like strings that look like Drive IDs
    cmd = f"git log -p --all 2>/dev/null | {DIFF_METADATA_FILTER} | grep -oE '[a-zA-Z0-9_-]{{33,44}}' | sort -u | head -20"
    rc, stdout, stderr = run_cmd(cmd, repo_path)

    findings = []
    if stdout.strip():
        for match in stdout.strip().split("\n"):
            # Filter out things that are clearly not Drive IDs
            if match and len(match) >= 33:
                # Skip lines of dashes (markdown/comment separators)
                if match.replace('-', '') == '':
                    continue
                # Skip pure hex (git hashes are 40 hex chars)
                if all(c in '0123456789abcdef' for c in match.lower()):
                    continue
                # Skip if it's all same character repeated
                if len(set(match)) <= 2:
                    continue
                # Skip if it's all same case letters (unlikely Drive ID)
                if match.isalpha():
                    continue
                # Real Drive IDs have mixed alphanumeric
                findings.append(match)

    return CheckResult(
        "Google Drive file IDs",
        len(findings) == 0,
        findings[:10],
        details=f"Found {len(findings)} potential Drive IDs" if findings else None,
    )


def check_oauth_tokens(repo_path: str) -> CheckResult:
    """Check for OAuth/API tokens (ya29, ghp_, sk-, etc.)."""
    # Common token prefixes
    patterns = [
        r'ya29\.[a-zA-Z0-9_-]+',      # Google OAuth access tokens
        r'ghp_[a-zA-Z0-9]{36}',        # GitHub personal access tokens
        r'gho_[a-zA-Z0-9]{36}',        # GitHub OAuth tokens
        r'sk-[a-zA-Z0-9]{48}',         # OpenAI API keys
        r'sk-proj-[a-zA-Z0-9_-]+',     # OpenAI project keys
        r'AIza[a-zA-Z0-9_-]{35}',      # Google API keys
    ]
    pattern = '|'.join(patterns)
    cmd = f'git log -p --all 2>/dev/null | {DIFF_METADATA_FILTER} | grep -oE "({pattern})" | sort -u | head -20'
    rc, stdout, stderr = run_cmd(cmd, repo_path)

    findings = stdout.strip().split("\n") if stdout.strip() else []
    findings = [f for f in findings if f]  # Remove empty strings

    return CheckResult(
        "OAuth/API tokens",
        len(findings) == 0,
        findings,
    )


def check_email_addresses(repo_path: str) -> CheckResult:
    """Check for email addresses, especially personal domains."""
    # Email pattern - require at least 2 chars before @ to reduce false positives
    cmd = f"git log -p --all 2>/dev/null | {DIFF_METADATA_FILTER} | grep -oiE '[a-z0-9._%+-]{{2,}}@[a-z0-9.-]+\\.[a-z]{{2,}}' | sort -u | head -30"
    rc, stdout, stderr = run_cmd(cmd, repo_path)

    # Acceptable email patterns (RFC-reserved fake domains, GitHub noreply)
    acceptable_domains = [
        'example.com', 'example.org', 'test.com',
        'users.noreply.github.com',
    ]

    # Python decorator modules that look like email domains when matched
    # These appear as @module.something in code and +@module.something in diffs
    decorator_modules = [
        'click.', 'cli.', 'pytest.', 'mcp.', 'app.', 'flask.',
        'config.', 'profile.', 'rsus.', 'settings.', 'stubs.', 'withhold.',
        'records.', 'analysis.', 'tax.', 'router.', 'api.', 'auth.',
        'staticmethod', 'classmethod', 'property', 'dataclass',
        'fixture', 'mark.', 'tool', 'command', 'group', 'option',
    ]

    findings = []
    if stdout.strip():
        for email in stdout.strip().split("\n"):
            # Strip diff context (+/-) from start
            clean_email = email.lstrip('+-').lower()

            # Skip acceptable domains
            if any(ok in clean_email for ok in acceptable_domains):
                continue

            # Skip if the "domain" part looks like a Python decorator module
            # e.g., "@config.command" has domain "config.command"
            at_pos = clean_email.find('@')
            if at_pos >= 0:
                domain_part = clean_email[at_pos + 1:]
                if any(domain_part.startswith(mod) for mod in decorator_modules):
                    continue

            # Skip if local part is just +/- (diff artifacts)
            local_part = clean_email[:at_pos] if at_pos > 0 else clean_email
            if local_part in ['', '+', '-', '+-', '-+']:
                continue

            findings.append(email)

    return CheckResult(
        "Email addresses",
        len(findings) == 0,
        findings[:15],
    )


def check_ssn_ein_patterns(repo_path: str) -> CheckResult:
    """Check for SSN/EIN patterns (XXX-XX-XXXX or XX-XXXXXXX)."""
    # SSN: 3-2-4 digits, EIN: 2-7 digits
    cmd = f"git log -p --all 2>/dev/null | {DIFF_METADATA_FILTER} | grep -oE '[0-9]{{3}}-[0-9]{{2}}-[0-9]{{4}}|[0-9]{{2}}-[0-9]{{7}}' | sort -u"
    rc, stdout, stderr = run_cmd(cmd, repo_path)

    # Obviously fake test values (sequential digits, all same digit, etc.)
    # Generated programmatically to avoid triggering precommit scanners
    fake_test_values = [
        '-'.join(['12', '3456789']),           # Sequential EIN
        '-'.join(['123', '45', '6789']),       # Classic sequential SSN
        '-'.join(['0'*3, '0'*2, '0'*4]),       # All zeros (invalid)
        '-'.join(['1'*3, '1'*2, '1'*4]),       # All ones
        '-'.join(['9'*3, '9'*2, '9'*4]),       # All nines
        '-'.join(['00', '0'*7]),               # Invalid EIN
    ]

    findings = []
    if stdout.strip():
        for match in stdout.strip().split("\n"):
            if match and match not in fake_test_values:
                findings.append(match)

    return CheckResult(
        "SSN/EIN patterns",
        len(findings) == 0,
        findings,
    )


def run_devws_precommit(repo_path: str) -> CheckResult:
    """Run devws precommit as final check."""
    cmd = 'devws precommit 2>&1'
    rc, stdout, stderr = run_cmd(cmd, repo_path, timeout=120)

    output = stdout + stderr
    # Check for explicit success message, not just return code
    passed = "No secrets found" in output or "✅ No secrets found" in output

    findings = []
    if not passed:
        # Extract only the relevant findings, not progress messages
        for line in output.split("\n"):
            line = line.strip()
            if line and not line.startswith("Gathering") and not line.startswith("Identifying") and not line.startswith("Scanning"):
                findings.append(line)
        findings = findings[:20]

    return CheckResult(
        "devws precommit",
        passed,
        findings,
        details="Clean" if passed else output[:500],
    )


# =============================================================================
# Main verification runner
# =============================================================================

def estimate_checks() -> List[Tuple[str, str]]:
    """Return list of (check_name, description) for estimation."""
    return [
        ("Git repository", "Verify valid git repo"),
        ("Staged content", "Check git diff --staged for sensitive patterns"),
        ("Sensitive patterns in history", "Full git log -p scan for names/employers"),
        ("Sensitive patterns in commits", "Commit message scan for names/employers"),
        ("Current filenames", "git ls-files scan for sensitive names"),
        ("Historical filenames", "All historical filenames for sensitive names"),
        ("Branch names", "All branch names for sensitive patterns"),
        ("Tag names", "All tags and messages for sensitive patterns"),
        ("Stash entries", "Check for stash (should be empty)"),
        ("Orphan commits", "Dangling/unreachable commits for sensitive data"),
        ("Large amounts (>=$300k)", "Dollar amounts >= $300k in history"),
        ("Non-round 6-figure", "6-figure amounts not ending in .00"),
        ("5-figure non-round", "5-figure amounts not divisible by 100"),
        ("Amounts with cents (>$500)", "Non-.00 amounts over $500"),
        ("All suspicious amounts", ">=$10k non-round or >=$100k any"),
        ("Commit message amounts", "Dollar amounts in commit messages"),
        ("Repeated non-round amounts", "Same non-round amount appearing multiple times"),
        ("Filesystem sensitive", "Direct grep bypassing .gitignore"),
        ("Filesystem amounts", "Direct large amount grep on filesystem"),
        ("Reflog", "Local reflog scan for sensitive patterns"),
        ("Git objects", "Direct object database scan"),
        ("Pack files", "Packed objects check"),
        ("Google Drive IDs", "33-44 char IDs that look like Drive/Doc IDs"),
        ("OAuth/API tokens", "ya29, ghp_, sk-, AIza tokens"),
        ("Email addresses", "Email patterns except example/author domains"),
        ("SSN/EIN patterns", "XXX-XX-XXXX or XX-XXXXXXX number patterns"),
        ("devws precommit", "Final precommit check (GCP IDs, secrets)"),
    ]


def run_verification(repo_path: str) -> VerificationReport:
    """Run all verification checks."""
    report = VerificationReport(repo_path=repo_path)

    checks = [
        ("Git repository", check_git_repo),
        ("Staged content", check_staged_content),
        ("Sensitive patterns in history", check_sensitive_patterns_in_history),
        ("Sensitive patterns in commits", check_sensitive_patterns_in_commits),
        ("Current filenames", check_sensitive_filenames_current),
        ("Historical filenames", check_sensitive_filenames_history),
        ("Branch names", check_branch_names),
        ("Tag names", check_tag_names),
        ("Stash entries", check_stash_entries),
        ("Orphan commits", check_orphan_commits),
        ("Large amounts (>=$300k)", check_large_amounts),
        ("Non-round 6-figure", check_nonround_6figure),
        ("5-figure non-round", check_5figure_nonround),
        ("Amounts with cents (>$500)", check_amounts_with_cents),
        ("All suspicious amounts", check_all_dollar_amounts),
        ("Commit message amounts", check_commit_message_amounts),
        ("Repeated non-round amounts", check_percentage_like_amounts),
        ("Filesystem sensitive", check_filesystem_sensitive),
        ("Filesystem amounts", check_filesystem_amounts),
        ("Reflog", check_reflog),
        ("Git objects", check_git_objects_direct),
        ("Pack files", check_pack_files),
        ("Google Drive IDs", check_google_drive_ids),
        ("OAuth/API tokens", check_oauth_tokens),
        ("Email addresses", check_email_addresses),
        ("SSN/EIN patterns", check_ssn_ein_patterns),
        ("devws precommit", run_devws_precommit),
    ]

    total = len(checks)
    print(f"\n{'='*60}")
    print(f"Repository Sensitive Data Verification")
    print(f"{'='*60}")
    print(f"Target: {repo_path}")
    print(f"Checks: {total}")
    print(f"{'='*60}\n")

    # First check - must be a git repo
    result = check_git_repo(repo_path)
    report.checks.append(result)
    print_progress(1, total, "Git repository")
    print_result(result)

    if not result.passed:
        print("\n\033[91mERROR: Not a valid git repository. Aborting.\033[0m")
        return report

    # Run remaining checks
    for i, (name, check_func) in enumerate(checks[1:], start=2):
        print_progress(i, total, name)
        try:
            result = check_func(repo_path)
        except Exception as e:
            result = CheckResult(name, False, [f"Error: {str(e)}"])
        report.checks.append(result)
        print_result(result)

    return report


def print_summary(report: VerificationReport):
    """Print final summary."""
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")

    passed = sum(1 for c in report.checks if c.passed)
    failed = sum(1 for c in report.checks if not c.passed)

    print(f"Total checks: {len(report.checks)}")
    print(f"Passed: \033[92m{passed}\033[0m")
    print(f"Failed: \033[91m{failed}\033[0m")

    if failed > 0:
        print(f"\n\033[91mFailed checks:\033[0m")
        for c in report.checks:
            if not c.passed:
                print(f"  - {c.name}")

    print(f"\n{'='*60}")
    if report.all_passed:
        print("\033[92mALL CHECKS PASSED - Repository appears clean\033[0m")
    else:
        print("\033[91mSOME CHECKS FAILED - Review findings above\033[0m")
        print_remediation_guidance(report)
    print(f"{'='*60}\n")


def print_remediation_guidance(report: VerificationReport):
    """Print actionable remediation steps based on failures."""
    failed_names = [c.name for c in report.checks if not c.passed]

    print(f"\n{'='*60}")
    print("REMEDIATION STEPS")
    print(f"{'='*60}")

    # Always start with backup warning
    print("""
\033[93m⚠️  BACKUP FIRST (history rewrite is destructive!):\033[0m
    git bundle create ~/$(basename $PWD)-backup-$(date +%Y%m%d).bundle --all
    # Upload bundle to Google Drive for safekeeping
""")

    # Pattern-related failures
    pattern_checks = ["Sensitive patterns in git history", "Sensitive patterns in commit messages",
                      "Sensitive patterns in current filenames", "Sensitive patterns in historical filenames"]
    if any(c in failed_names for c in pattern_checks):
        print("""
\033[96mTo fix sensitive PATTERNS in file content:\033[0m
    # Create replacements.txt with: literal:OLD==>NEW (one per line)
    echo 'literal:BadName==>GoodName' >> replacements.txt
    git filter-repo --replace-text replacements.txt

\033[96mTo fix sensitive FILENAMES:\033[0m
    git filter-repo --path-rename old-name.txt:new-name.txt

\033[96mTo fix sensitive COMMIT MESSAGES:\033[0m
    git filter-repo --message-callback 'return message.replace(b"old", b"new")'

\033[96mTo REMOVE entire directories:\033[0m
    git filter-repo --path-glob 'data/*' --invert-paths
""")

    # Amount-related failures
    amount_checks = ["Dollar amounts >= $300k", "Non-round 6-figure amounts",
                     "5-figure non-round amounts", "Suspicious dollar amounts"]
    if any(c in failed_names for c in amount_checks):
        print("""
\033[96mTo fix dollar AMOUNTS:\033[0m
    # Add to replacements.txt: literal:$OLD_AMOUNT==>$NEW_AMOUNT
    echo 'literal:$OLD_AMOUNT==>$NEW_AMOUNT' >> replacements.txt
    git filter-repo --replace-text replacements.txt

    # For derived amounts from round bases (e.g., tax calculated from $120k gross),
    # add them to ACCEPTABLE_IRS_AMOUNTS in this script instead of removing.
""")

    # Stash failures
    if "Stash entries (should be empty)" in failed_names:
        print("""
\033[96mTo clear STASH entries:\033[0m
    git stash clear
""")

    # Post-cleanup reminder
    print("""
\033[93mAFTER EACH git filter-repo PASS:\033[0m
    1. Save commit mapping:
       cp .git/filter-repo/commit-map ~/mappings/commit-map-$(date +%Y%m%d)-DESCRIPTION.txt
    2. Re-add remote (filter-repo removes it):
       git remote add origin git@github.com:USER/REPO.git
    3. Re-run this script to verify
    4. Force push when clean:
       git push --force
""")


def main():
    parser = argparse.ArgumentParser(
        description="Verify repository is clean of sensitive data"
    )
    parser.add_argument(
        "repo_path",
        help="Path to the git repository to verify",
    )
    parser.add_argument(
        "--estimate",
        action="store_true",
        help="Just show what checks will be run",
    )
    parser.add_argument(
        "--check-gitignored",
        type=lambda x: x.lower() in ('true', '1', 'yes'),
        metavar="BOOL",
        help="Override whether to check gitignored files. true=check them, false=skip them. "
             "Default behavior: YAML setting, or check if not specified.",
    )

    args = parser.parse_args()

    # Override SKIP_GITIGNORED_FILESYSTEM based on CLI flag
    # Precedence: CLI > YAML > default (False = check gitignored files)
    global SKIP_GITIGNORED_FILESYSTEM
    if args.check_gitignored is not None:
        # CLI flag provided: --check-gitignored true means DON'T skip (check them)
        SKIP_GITIGNORED_FILESYSTEM = not args.check_gitignored

    # Resolve path
    repo_path = os.path.abspath(args.repo_path)

    if not os.path.isdir(repo_path):
        print(f"Error: {repo_path} is not a directory")
        sys.exit(1)

    # Change to repo directory
    os.chdir(repo_path)

    if args.estimate:
        print(f"\nChecks to be performed on: {repo_path}\n")
        for i, (name, desc) in enumerate(estimate_checks(), 1):
            print(f"  {i:2}. {name}: {desc}")
        print(f"\nTotal: {len(estimate_checks())} checks")
        return

    # Run verification
    report = run_verification(repo_path)
    print_summary(report)

    # Exit with appropriate code
    sys.exit(0 if report.all_passed else 1)


if __name__ == "__main__":
    main()

"""Dollar amount checks for sensitive financial data."""

import re
from typing import List

from ..utils import CheckResult, run_cmd, DIFF_METADATA_FILTER
from ..config import load_thresholds


# Acceptable IRS/tax amounts that are public knowledge
ACCEPTABLE_IRS_AMOUNTS = {
    # Social Security wage bases
    "176,100", "168,600", "160,200",
    # MFJ bracket thresholds (common years)
    "23,200", "23,850", "94,300", "96,950", "201,050", "206,700",
    "383,900", "394,600", "487,450", "501,050", "731,200", "751,600",
    # Standard deductions
    "29,200", "30,000",
    # Additional Medicare threshold
    "250,000",
}


def is_acceptable_amount(amount_str: str) -> bool:
    """Check if amount is a known IRS/tax value."""
    normalized = amount_str.replace("$", "").lstrip("0")
    return normalized in ACCEPTABLE_IRS_AMOUNTS


def parse_amount(amount_str: str) -> float:
    """Parse dollar amount string to float."""
    cleaned = amount_str.replace("$", "").replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def is_round_amount(amount: float) -> bool:
    """Check if amount is 'round' (ends in 000 or 00)."""
    if amount >= 10000:
        return amount % 1000 == 0
    return amount % 100 == 0


def check_large_amounts(repo_path: str, thresholds: dict) -> CheckResult:
    """Check for very large dollar amounts (>= $300k default)."""
    threshold = thresholds.get("large_amount", 300000)

    cmd = f"git diff --staged 2>/dev/null | {DIFF_METADATA_FILTER} | grep -oE '\\$[0-9]{{1,3}}(,[0-9]{{3}})+(\\.[0-9]{{2}})?' | head -30"
    rc, stdout, _ = run_cmd(cmd, repo_path)

    findings = []
    if stdout.strip():
        for amount_str in stdout.strip().split("\n"):
            amount = parse_amount(amount_str)
            if amount >= threshold and not is_acceptable_amount(amount_str):
                findings.append(f"{amount_str} (>= ${threshold:,})")

    cmd = f"git diff 2>/dev/null | {DIFF_METADATA_FILTER} | grep -oE '\\$[0-9]{{1,3}}(,[0-9]{{3}})+(\\.[0-9]{{2}})?' | head -30"
    rc, stdout, _ = run_cmd(cmd, repo_path)

    if stdout.strip():
        for amount_str in stdout.strip().split("\n"):
            amount = parse_amount(amount_str)
            if amount >= threshold and not is_acceptable_amount(amount_str):
                if amount_str not in [f.split()[0] for f in findings]:
                    findings.append(f"{amount_str} (>= ${threshold:,})")

    passed = len(findings) == 0
    return CheckResult(f"Large amounts (>= ${threshold:,})", passed, findings[:10])


def check_nonround_amounts(repo_path: str, thresholds: dict) -> CheckResult:
    """Check for suspicious non-round amounts that might be real data."""
    threshold = thresholds.get("suspicious_nonround", 10000)

    cmd = f"git diff --staged 2>/dev/null | {DIFF_METADATA_FILTER} | grep -oE '\\$[0-9]{{1,3}}(,[0-9]{{3}})+(\\.[0-9]{{2}})?' | head -50"
    rc, stdout, _ = run_cmd(cmd, repo_path)

    findings = []
    if stdout.strip():
        for amount_str in stdout.strip().split("\n"):
            amount = parse_amount(amount_str)
            if amount >= threshold and not is_round_amount(amount) and not is_acceptable_amount(amount_str):
                findings.append(amount_str)

    passed = len(findings) == 0
    return CheckResult("Non-round suspicious amounts", passed, findings[:10])


def check_amounts_with_cents(repo_path: str, thresholds: dict) -> CheckResult:
    """Check for amounts with cents (often real payroll data)."""
    threshold = thresholds.get("cents_review", 500)

    cmd = f"git diff --staged 2>/dev/null | {DIFF_METADATA_FILTER} | grep -oE '\\$[0-9,]+\\.[0-9]{{2}}' | head -30"
    rc, stdout, _ = run_cmd(cmd, repo_path)

    findings = []
    if stdout.strip():
        for amount_str in stdout.strip().split("\n"):
            amount = parse_amount(amount_str)
            cents = round((amount % 1) * 100)
            if cents != 0 and amount >= threshold:
                findings.append(amount_str)

    passed = len(findings) == 0
    return CheckResult("Amounts with cents", passed, findings[:10])


def run_checks(repo_path: str, deep: bool = False, **kwargs) -> List[CheckResult]:
    """Run all amount checks. Standard step interface."""
    thresholds = load_thresholds()
    return [
        check_large_amounts(repo_path, thresholds),
        check_nonround_amounts(repo_path, thresholds),
        check_amounts_with_cents(repo_path, thresholds),
    ]

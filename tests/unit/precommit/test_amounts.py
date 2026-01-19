"""Tests for SDK scanner amount checks - via run_scan(only_check='amounts')."""
import subprocess
from agentic_consult.sdk.scanner.core import run_scan
from agentic_consult.sdk.scanner.steps.amounts import is_acceptable_amount

# Build test amounts via math to avoid literal patterns in source
TEST_LARGE = 500 * 1000
TEST_CENTS = 3847 + 0.23
TEST_NONROUND_1 = 175 * 1000 + 432
TEST_NONROUND_2 = 123 * 1000 + 456

# Check names that belong to the amounts module (Large amounts name includes threshold)
AMOUNT_CHECK_NAMES = {
    "Non-round suspicious amounts",
    "Amounts with cents",
}


def is_amounts_check(name: str) -> bool:
    """Check if name belongs to amounts module (handles dynamic Large amounts name)."""
    if name in AMOUNT_CHECK_NAMES:
        return True
    if name.startswith("Large amounts (>="):
        return True
    return False


def assert_only_amounts_module(report):
    """Assert report contains only amount checks (plus Git repository)."""
    for check in report.checks:
        assert check.name == "Git repository" or is_amounts_check(check.name), \
            f"Unexpected check '{check.name}' - only amounts module should run"


def test_large_amount_detected_in_staged(tmp_path):
    """Large dollar amounts in staged content are flagged."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

    (repo / "data.txt").write_text(f"Total: ${TEST_LARGE:,.2f}")
    subprocess.run(["git", "-C", str(repo), "add", "data.txt"], check=True)

    report = run_scan(str(repo), only_check="amounts")

    # Verify only amounts module ran
    assert_only_amounts_module(report)

    # Verify finding detected
    assert report.failed
    large = next(c for c in report.checks if c.name.startswith("Large amounts"))
    assert not large.passed
    assert any(f"{TEST_LARGE:,}" in f for f in large.findings)


def test_amount_with_cents_detected_in_staged(tmp_path):
    """Amounts with cents (payroll-like) in staged content are flagged."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

    (repo / "payroll.txt").write_text(f"Net pay: ${TEST_CENTS:,.2f}")
    subprocess.run(["git", "-C", str(repo), "add", "payroll.txt"], check=True)

    report = run_scan(str(repo), only_check="amounts")

    assert_only_amounts_module(report)
    assert report.failed
    cents = next(c for c in report.checks if "cents" in c.name.lower())
    assert not cents.passed
    assert any(f"{TEST_CENTS:,.2f}" in f for f in cents.findings)


def test_irs_amounts_not_flagged():
    """Known IRS threshold amounts are acceptable."""
    # SS wage base - should be acceptable
    assert is_acceptable_amount("$176,100") == True
    assert is_acceptable_amount("176,100") == True

    # Random large amount - not acceptable
    assert is_acceptable_amount(f"${TEST_NONROUND_1:,}") == False
    assert is_acceptable_amount(f"${TEST_NONROUND_2:,}") == False

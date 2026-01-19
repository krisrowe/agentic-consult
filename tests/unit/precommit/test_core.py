"""Tests for SDK scanner core - run_scan orchestration and validation."""
import subprocess
import sys
import os
import pytest
from unittest.mock import patch

from agentic_consult.sdk.scanner.core import run_scan, InvalidCheckModuleError
from agentic_consult.sdk.scanner.steps import get_step_names
from agentic_consult.sdk.scanner.steps.devws import run_devws_precommit
from agentic_consult.sdk.scanner.utils import CheckResult

# Build SSN via concatenation to avoid literal pattern in source
TEST_SSN = "123" + "-" + "45" + "-" + "6789"


def test_only_check_invalid_module_error(tmp_path):
    """run_scan raises InvalidCheckModuleError for unknown module names."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

    with pytest.raises(InvalidCheckModuleError) as exc_info:
        run_scan(str(repo), only_check="bogus_module")

    assert "bogus_module" in str(exc_info.value)
    assert "Valid modules" in str(exc_info.value)


def test_valid_check_modules_constant():
    """get_step_names() returns expected module names."""
    step_names = get_step_names()
    assert "user" in step_names
    assert "amounts" in step_names
    assert "devws" in step_names
    assert "ssn_ein" in step_names
    assert "emails" in step_names


@patch("agentic_consult.sdk.scanner.steps.devws.run_cmd")
def test_devws_precommit_success(mock_run_cmd):
    """devws precommit success returns passed CheckResult."""
    mock_run_cmd.return_value = (0, "All checks passed", "")

    result = run_devws_precommit("/fake/path")

    assert result.passed
    assert result.name == "devws precommit"


@patch("agentic_consult.sdk.scanner.steps.devws.run_cmd")
def test_devws_precommit_failure_captured(mock_run_cmd):
    """devws precommit failure is captured with findings."""
    mock_run_cmd.return_value = (1, "[!] FOUND: sensitive data\n- file.txt:1 secret", "")

    result = run_devws_precommit("/fake/path")

    assert not result.passed
    assert len(result.findings) > 0


# --- CLI Exit Code Integration Tests ---

def test_cli_exit_zero_when_sdk_scanner_passes(tmp_path):
    """CLI exits 0 when SDK scanner finds nothing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

    # Create clean file and stage it
    (repo / "clean.txt").write_text("Nothing sensitive here")
    subprocess.run(["git", "-C", str(repo), "add", "clean.txt"], check=True)

    proc = subprocess.run(
        [sys.executable, "-m", "agentic_consult", "precommit", str(repo)],
        cwd=str(repo),
        capture_output=True,
        text=True
    )

    assert proc.returncode == 0, f"Expected exit 0, got {proc.returncode}\n{proc.stdout}\n{proc.stderr}"


def test_cli_exit_nonzero_when_sdk_scanner_finds_ssn(tmp_path):
    """CLI exits non-zero when SDK scanner detects SSN pattern."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

    # Create file with SSN pattern and stage it
    (repo / "data.txt").write_text(f"SSN: {TEST_SSN}")
    subprocess.run(["git", "-C", str(repo), "add", "data.txt"], check=True)

    proc = subprocess.run(
        [sys.executable, "-m", "agentic_consult", "precommit", str(repo)],
        cwd=str(repo),
        capture_output=True,
        text=True
    )

    assert proc.returncode != 0, f"Expected non-zero exit, got 0\n{proc.stdout}\n{proc.stderr}"
    assert TEST_SSN in proc.stdout or "SSN" in proc.stdout.upper()

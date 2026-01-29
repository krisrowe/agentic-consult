"""Tests for SDK scanner identifier checks - ssn_ein, oauth_tokens, emails, drive_ids steps."""
import subprocess
from agentic_consult.sdk.scanner.core import run_scan

# Build test patterns via concatenation to avoid literal patterns in source
TEST_SSN = "123" + "-" + "45" + "-" + "6789"
TEST_EIN = "12" + "-" + "3456789"


def test_ssn_pattern_detected_in_staged(tmp_path):
    """SSN-like patterns in staged content are flagged."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

    (repo / "data.txt").write_text(f"SSN: {TEST_SSN}")
    subprocess.run(["git", "-C", str(repo), "add", "data.txt"], check=True)

    report = run_scan(str(repo), only_check="ssn_ein")

    assert report.failed
    ssn = next(c for c in report.checks if c.name == "SSN/EIN patterns")
    assert not ssn.passed
    assert any(TEST_SSN in f for f in ssn.findings)


def test_ein_pattern_detected_in_staged(tmp_path):
    """EIN-like patterns in staged content are flagged."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

    (repo / "data.txt").write_text(f"EIN: {TEST_EIN}")
    subprocess.run(["git", "-C", str(repo), "add", "data.txt"], check=True)

    report = run_scan(str(repo), only_check="ssn_ein")

    assert report.failed
    ssn = next(c for c in report.checks if c.name == "SSN/EIN patterns")
    assert not ssn.passed
    assert any(TEST_EIN in f for f in ssn.findings)


def test_gh_pat_detected_in_staged(tmp_path):
    """GitHub PAT tokens in staged content are flagged."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

    fake_pat = "ghp_" + "a" * 36
    (repo / "config.txt").write_text(f"token: {fake_pat}")
    subprocess.run(["git", "-C", str(repo), "add", "config.txt"], check=True)

    report = run_scan(str(repo), only_check="oauth_tokens")

    assert report.failed
    oauth = next(c for c in report.checks if c.name == "OAuth/API tokens")
    assert not oauth.passed
    assert any("GitHub PAT" in f for f in oauth.findings)


def test_allowed_email_not_flagged(tmp_path):
    """Allowed email addresses in staged content are not flagged."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

    (repo / "notes.txt").write_text("Contact: user@example.com")
    subprocess.run(["git", "-C", str(repo), "add", "notes.txt"], check=True)

    report = run_scan(str(repo), only_check="emails")

    emails = next(c for c in report.checks if c.name == "Email addresses")
    assert emails.passed


def test_non_allowed_email_flagged(tmp_path, monkeypatch):
    """Email not in test config's allowed list is flagged."""
    import yaml

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

    # Override config with limited allowed_emails (non-RFC domains)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "app.yaml").write_text(yaml.dump({
        "precommit": {"allowed_emails": ["test@fake.com", "test@testcorp.com"]}
    }))
    monkeypatch.setenv("CONSULT_CONFIG_DIR", str(config_dir))

    # user@gmail.com is allowed in real config but not in test config
    (repo / "notes.txt").write_text("Contact: user@gmail.com")
    subprocess.run(["git", "-C", str(repo), "add", "notes.txt"], check=True)

    report = run_scan(str(repo), only_check="emails")

    emails = next(c for c in report.checks if c.name == "Email addresses")
    assert not emails.passed
    assert any("gmail" in f for f in emails.findings)



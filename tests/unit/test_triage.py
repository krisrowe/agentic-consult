"""
Sociable unit test for email triage.

Tests the full triage flow end-to-end with mock data at network boundaries only.

NOTE: conftest.py auto-sets CONSULT_CONFIG_DIR for every test.
Use the `config_dir` fixture to get the isolated config path.
"""
import json
from pathlib import Path
from datetime import datetime

import pytest
import yaml
from email_archive import EmailStore


def test_end_to_end(config_dir, tmp_path, monkeypatch):
    """
    Test triage_emails SDK function end-to-end.

    Uses fake emails and fake Gemini response via config flags.
    Real file system, real code paths, mock only at network I/O.
    """
    # Setup data directory (config_dir is already set by conftest)
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Setup cache directory
    cache_home = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
    monkeypatch.setenv("EMAIL_ARCHIVE_DATA_DIR", str(data_dir))

    email_config = {
        "use_mock_emails": True,
        "use_mock_gemini": True,  # Still needed for suggest_action or fallback
        "rules": [
            {
                "id": "test-archive",
                "action": "archive",
                "condition": "Email is a newsletter",
            },
        ],
    }
    (config_dir / "email.yaml").write_text(yaml.dump(email_config))

    from agentic_consult.email.triage import triage_emails, get_cached_emails

    # 1. Populate Store (Mocking the background analyzer)
    store = EmailStore(data_dir)

    # Email 1: Newsletter -> Archive
    store.save(
        "msg-001",
        datetime.utcnow(),
        {"Subject": "Weekly Newsletter", "From": "sender@example.com"},
        {"body_text": "Content"}
    )
    store.save_sidecar("msg-001", "analysis.json", {
        "id": "msg-001",
        "recommended_action": "archive_now",
        "rule_id": "test-archive",
        "reason": "Newsletter matches archive rule",
        "audience": "BROADCAST"
    })

    # Email 2: Failed Payment -> Review
    store.save(
        "msg-002",
        datetime.utcnow(),
        {"Subject": "Payment Failed", "From": "bank@example.com"},
        {"body_text": "Your payment failed."}
    )
    store.save_sidecar("msg-002", "analysis.json", {
        "id": "msg-002",
        "recommended_action": "review",
        "rule_id": "sys-payment-failed",
        "reason": "Payment failure detected",
        "audience": "DIRECT"
    })

    # Run full triage
    result = triage_emails(review_status="all", limit=10)

    # Verify
    assert "error" not in result, f"Error: {result.get('error')}"
    assert len(result["emails"]) == 2

    recs = {r["id"]: r for r in result["emails"]}

    assert recs["msg-001"]["recommended_action"] == "archive_now"
    assert recs["msg-002"]["recommended_action"] == "review"

    # Verify instructions were generated
    assert "Triage Suggestions" in result["instructions"]

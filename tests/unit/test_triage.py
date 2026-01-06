"""
Sociable unit test for email triage.

Tests the full triage flow end-to-end with mock data at network boundaries only.
"""

import json
import os
import tempfile
from pathlib import Path

import yaml


def test_end_to_end():
    """
    Test triage_emails SDK function end-to-end.

    Uses fake emails and fake Gemini response via config flags.
    Real file system, real code paths, mock only at network I/O.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # Setup directories
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        cache_home = tmp_path / "cache"
        # The code uses get_cache_dir() / "emails"
        # get_cache_dir() uses XDG_CACHE_HOME / "agentic-consult"
        cache_dir = cache_home / "agentic-consult" / "emails"
        cache_dir.mkdir(parents=True)

        # Fake emails - these need to be in the CACHE dir as individual json files
        # for get_cached_emails to find them, OR we use the mock_emails logic
        # but the test calls get_cached_emails at the end.

        email_config = {
            "use_mock_emails": True,
            "use_mock_gemini": True,
            "rules": [
                {
                    "id": "test-archive",
                    "action": "archive",
                    "condition": "Email is a newsletter",
                },
            ],
        }
        (config_dir / "email.yaml").write_text(yaml.dump(email_config))

        # Fake emails
        mock_emails = [
            {
                "id": "msg-001",
                "thread_id": "thread-001",
                "date": "2026-01-04",
                "from": "newsletter@example.com",
                "to": "user@example.com",
                "subject": "Weekly Newsletter",
                "body": "Newsletter content here.",
                "labels": ["INBOX"],
            },
            {
                "id": "msg-002",
                "thread_id": "thread-002",
                "date": "2026-01-04",
                "from": "bank@example.com",
                "to": "user@example.com",
                "subject": "Payment Failed",
                "body": "Your payment failed.",
                "labels": ["INBOX"],
            },
        ]
        (cache_dir / "mock-triage-emails.json").write_text(json.dumps(mock_emails))

        # Fake Gemini response
        mock_response = {
            "emails": [
                {
                    "id": "msg-001",
                    "date": "2026-01-04",
                    "from": "newsletter@example.com",
                    "subject": "Weekly Newsletter",
                    "recommended_action": "archive",
                    "rule_id": "test-archive",
                    "reason": "Newsletter matches archive rule",
                },
                {
                    "id": "msg-002",
                    "date": "2026-01-04",
                    "from": "bank@example.com",
                    "subject": "Payment Failed",
                    "recommended_action": "review",
                    "rule_id": "sys-payment-failed",
                    "reason": "Payment failure detected",
                },
            ]
        }
        (cache_dir / "mock-triage-response.json").write_text(json.dumps(mock_response))

        # Set env vars
        old_config_dir = os.environ.get("CONSULT_CONFIG_DIR")
        old_cache_home = os.environ.get("XDG_CACHE_HOME")

        try:
            os.environ["CONSULT_CONFIG_DIR"] = str(config_dir)
            os.environ["XDG_CACHE_HOME"] = str(cache_home)

            from agentic_consult.email.triage import triage_emails, get_cached_emails, cache_email

            # Cache the mock emails so they can be retrieved
            for email in mock_emails:
                cache_email(email)

            # Run full triage
            result = triage_emails(review_status="all", limit=10)

            # Verify
            assert "error" not in result, f"Error: {result.get('error')}"
            assert len(result["emails"]) == 2

            recs = {r["id"]: r for r in result["emails"]}
            assert recs["msg-001"]["recommended_action"] == "archive"
            assert recs["msg-002"]["recommended_action"] == "review"

            # Verify caching worked
            cached = get_cached_emails(["msg-001", "msg-002"])
            assert len(cached["messages"]) == 2
            assert "error" not in cached["messages"][0]

        finally:
            if old_config_dir is not None:
                os.environ["CONSULT_CONFIG_DIR"] = old_config_dir
            else:
                os.environ.pop("CONSULT_CONFIG_DIR", None)

            if old_cache_home is not None:
                os.environ["XDG_CACHE_HOME"] = old_cache_home
            else:
                os.environ.pop("XDG_CACHE_HOME", None)

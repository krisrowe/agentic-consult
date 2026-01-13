"""
Sociable unit test for email triage.

Tests the full triage flow end-to-end with mock data at network boundaries only.
"""

import json
import os
import tempfile
from pathlib import Path
from datetime import datetime

import yaml
from email_archive import EmailStore


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
        
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        email_config = {
            "use_mock_emails": True,
            "use_mock_gemini": True, # Still needed for suggest_action or fallback
            "rules": [
                {
                    "id": "test-archive",
                    "action": "archive",
                    "condition": "Email is a newsletter",
                },
            ],
        }
        (config_dir / "email.yaml").write_text(yaml.dump(email_config))

        # Set env vars
        old_config_dir = os.environ.get("CONSULT_CONFIG_DIR")
        old_data_dir = os.environ.get("EMAIL_ARCHIVE_DATA_DIR")
        old_cache_home = os.environ.get("XDG_CACHE_HOME")

        try:
            os.environ["CONSULT_CONFIG_DIR"] = str(config_dir)
            os.environ["EMAIL_ARCHIVE_DATA_DIR"] = str(data_dir)
            # Also set cache home for non-email caches
            cache_home = tmp_path / "cache"
            os.environ["XDG_CACHE_HOME"] = str(cache_home)

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

        finally:
            if old_config_dir is not None:
                os.environ["CONSULT_CONFIG_DIR"] = old_config_dir
            else:
                os.environ.pop("CONSULT_CONFIG_DIR", None)
            
            if old_data_dir is not None:
                os.environ["EMAIL_ARCHIVE_DATA_DIR"] = old_data_dir
            else:
                os.environ.pop("EMAIL_ARCHIVE_DATA_DIR", None)
                
            if old_cache_home is not None:
                os.environ["XDG_CACHE_HOME"] = old_cache_home
            else:
                os.environ.pop("XDG_CACHE_HOME", None)
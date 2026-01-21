"""Tests for email analyzer service.

NOTE: conftest.py auto-sets CONSULT_CONFIG_DIR for every test.
"""
import pytest
import re
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from email_archive import EmailStore
from agentic_consult.email.analyzer import EmailAnalyzer


# --- Test Infrastructure ---

class DummyProvider:
    """Predictable provider for unit tests."""
    def analyze(self, email, prompt):
        return {
            "id": email["id"],
            "recommended_action": "review",
            "reason": f"Dummy processed: {email['subject']}",
            "audience": "DIRECT"
        }


class PromptCapturingProvider:
    """Provider that captures prompts for inspection."""
    def __init__(self):
        self.captured_prompts = []

    def analyze(self, email, prompt):
        self.captured_prompts.append(prompt)
        return {
            "id": email["id"],
            "recommended_action": "review",
            "reason": "Captured",
            "audience": "DIRECT"
        }


@pytest.fixture
def test_env(tmp_path):
    """Sets up an isolated data directory. Config dir is handled by conftest."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    store = EmailStore(data_dir)
    # Fixed reference date for deterministic testing
    ref_date = datetime(2026, 1, 12, 12, 0, 0)
    return store, data_dir, ref_date


# --- Targeted Proofs ---

def test_previously_analyzed_are_skipped(test_env):
    """Proof: Emails with existing .analysis.json sidecars are ignored."""
    store, _, ref_date = test_env
    msg_id = "already_done"
    store.save(msg_id, ref_date, {"Subject": "Done", "From": "user@example.com"}, {})
    # Manually create sidecar
    store.save_sidecar(msg_id, "analysis.json", {"status": "pre-existing"})

    analyzer = EmailAnalyzer(store, provider=DummyProvider())
    result = analyzer.process_queue(lookback_days=1, reference_date=ref_date)

    assert result["processed"] == 0
    assert result.get("status") == "idle"


def test_older_messages_skipped(test_env):
    """Proof: Emails older than the lookback window are ignored."""
    store, data_dir, ref_date = test_env
    old_id = "ancient_history"
    # 30 days before ref_date
    store.save(old_id, ref_date - timedelta(days=30), {"Subject": "Old", "From": "user@example.com"}, {})

    analyzer = EmailAnalyzer(store, provider=DummyProvider())
    result = analyzer.process_queue(lookback_days=7, reference_date=ref_date)

    assert result["processed"] == 0
    # Verification: check no analysis sidecar was created
    sidecars = list(data_dir.glob("*.analysis.json"))
    assert len(sidecars) == 0


def test_message_processing_limit(test_env):
    """Proof: The analyzer honors the batch 'limit' argument."""
    store, _, ref_date = test_env
    for i in range(5):
        store.save(f"msg_{i}", ref_date, {"Subject": f"Batch {i}", "From": "user@example.com"}, {})

    analyzer = EmailAnalyzer(store, provider=DummyProvider())
    result = analyzer.process_queue(limit=3, reference_date=ref_date)

    assert result["processed"] == 3


def test_ran_out_of_messages(test_env):
    """Proof: Returns idle status when no pending messages exist."""
    store, _, ref_date = test_env
    analyzer = EmailAnalyzer(store, provider=DummyProvider())
    result = analyzer.process_queue(reference_date=ref_date)

    assert result["processed"] == 0
    assert result["status"] == "idle"


# --- Integration / Multi-Cycle ---

def test_all_via_multiple_cycles(test_env):
    """
    Exhaustive proof: Verifies the entire state machine over multiple runs.
    Scenario: 10 emails spanning 10 days. 5 day window. Limit 3.
    """
    store, data_dir, ref_date = test_env
    # Prepping 10 emails (0 to 9 days old relative to ref_date)
    for i in range(10):
        date = ref_date - timedelta(days=i)
        store.save(f"m{i}", date, {"Subject": f"Email {i}", "From": "user@example.com"}, {})

    analyzer = EmailAnalyzer(store, provider=DummyProvider())

    # Window: 5 days lookback from ref_date (Jan 12).
    # Since we anchor to START OF DAY (00:00:00), 5 days lookback from Jan 12 is Jan 7 00:00:00.
    # m0 (Jan 12), m1 (11), m2 (10), m3 (9), m4 (8), m5 (7) are all >= Jan 7 00:00:00.
    # Total 6 emails visible.

    # Cycle 1: 3 of 6 visible are processed
    r1 = analyzer.process_queue(lookback_days=5, limit=3, reference_date=ref_date)
    assert r1["processed"] == 3

    # Cycle 2: Remaining 3 of 6 are processed
    r2 = analyzer.process_queue(lookback_days=5, limit=3, reference_date=ref_date)
    assert r2["processed"] == 3

    # Cycle 3: Queue exhausted
    r3 = analyzer.process_queue(lookback_days=5, limit=3, reference_date=ref_date)
    assert r3["processed"] == 0
    assert r3["status"] == "idle"

    # Leak Check: Exactly 6 total sidecars should exist
    sidecars = list(data_dir.glob("*.analysis.json"))
    assert len(sidecars) == 6


# --- Timezone Tests ---

def test_analyzer_uses_configured_timezone(config_dir, tmp_path):
    """
    Proof: The user_datetime in the prompt reflects the timezone from email.yaml.

    Tests two timezones 2 hours apart (UTC and Europe/Athens) by configuring
    each in email.yaml and verifying the prompt contains the correctly
    timezone-adjusted time.
    """
    from zoneinfo import ZoneInfo
    from unittest.mock import patch

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    store = EmailStore(data_dir)

    # Create a test email
    ref_date = datetime(2026, 1, 15, 12, 0, 0)
    store.save("tz-test", ref_date, {"Subject": "TZ Test", "From": "user@example.com"}, {"body_text": "Test body"})

    # Fixed UTC instant: 2026-01-15 18:30:00 UTC
    fixed_utc = datetime(2026, 1, 15, 18, 30, 0)

    def run_with_timezone(tz_name: str) -> str:
        """Run analyzer with given timezone and return captured prompt."""
        # Write email.yaml with timezone
        email_config = {
            "settings": {"timezone": tz_name},
            "rules": []
        }
        (config_dir / "email.yaml").write_text(yaml.dump(email_config))

        # Create timezone-aware datetime for the mock
        tz = ZoneInfo(tz_name)
        # Convert UTC instant to the target timezone
        aware_dt = fixed_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)

        provider = PromptCapturingProvider()

        # Remove sidecar so email is processed again
        for sidecar in data_dir.rglob("*.analysis.json"):
            sidecar.unlink()

        # Patch get_user_datetime to return our controlled time
        with patch('agentic_consult.email.analyzer.get_user_datetime', return_value=aware_dt):
            analyzer = EmailAnalyzer(store, provider=provider)
            analyzer.process_queue(lookback_days=7, limit=1, reference_date=ref_date)

        assert len(provider.captured_prompts) == 1
        return provider.captured_prompts[0]

    # Test with UTC (should show 18:30)
    prompt_utc = run_with_timezone("UTC")

    # Test with Europe/Athens (UTC+2, should show 20:30)
    prompt_athens = run_with_timezone("Europe/Athens")

    # Extract user_datetime from prompts
    utc_match = re.search(r"User's current datetime: (.+)", prompt_utc)
    athens_match = re.search(r"User's current datetime: (.+)", prompt_athens)

    assert utc_match, "Could not find user_datetime in UTC prompt"
    assert athens_match, "Could not find user_datetime in Athens prompt"

    utc_time = utc_match.group(1)
    athens_time = athens_match.group(1)

    # Verify they're different (2 hour difference)
    assert "18:30" in utc_time, f"Expected 18:30 in UTC time, got: {utc_time}"
    assert "20:30" in athens_time, f"Expected 20:30 in Athens time, got: {athens_time}"
    assert utc_time != athens_time, "Timezone should affect the datetime in prompt"

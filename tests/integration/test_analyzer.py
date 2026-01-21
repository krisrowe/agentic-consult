"""
Integration tests for email analyzer with real Gemini API.

Each test uses the full ruleset (system + bundles) with home-* enabled.
Tests verify:
- Correct rule matching (rule_id)
- Correct action (recommended_action)
- Original fields preserved (original.from, original.subject)
- Transformed fields (sender simplified, summary extracted)
- Field length limits (fit in table columns)
- Display date (exact value)

Requires: GEMINI_API_KEY in environment OR project_id for Secret Manager lookup.
"""
import pytest
import os
import json
import yaml
from datetime import datetime
from email_archive import EmailStore
from agentic_consult.email.analyzer import EmailAnalyzer
from agentic_consult.cloud import get_cloud_provider


# Shared email config that enables home-* rules
ENABLED_RULES_CONFIG = {
    "enable": ["home-*"],  # Enable all home bundle rules
}

# Column width limits for table display
MAX_SENDER_LEN = 25
MAX_SUMMARY_LEN = 50

# Fixed reference time for all tests: 2026-01-21 15:00:00 UTC (Tuesday)
# All email dates are set relative to this
REFERENCE_NOW = datetime(2026, 1, 21, 15, 0, 0)


@pytest.fixture
def gemini_api_key(real_project_id):
    """Get Gemini API key from env or Secret Manager."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key and real_project_id:
        api_key = get_cloud_provider().get_secret_value(real_project_id, "gemini-api-key")
    if not api_key:
        pytest.skip("GEMINI_API_KEY not set and no project_id for Secret Manager lookup.")
    return api_key


@pytest.fixture
def analyzer_env(tmp_path, config_dir, monkeypatch, gemini_api_key):
    """Setup isolated environment for analyzer tests."""
    monkeypatch.setenv("GEMINI_API_KEY", gemini_api_key)

    # Setup isolated email data directory
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("EMAIL_ARCHIVE_DATA_DIR", str(data_dir))

    # Enable home-* rules in isolated config
    (config_dir / "email.yaml").write_text(yaml.dump(ENABLED_RULES_CONFIG))

    # Mock get_user_datetime to return fixed reference time
    monkeypatch.setattr(
        "agentic_consult.email.triage.get_user_datetime",
        lambda: REFERENCE_NOW
    )

    store = EmailStore(data_dir)
    analyzer = EmailAnalyzer(store)

    return {"store": store, "analyzer": analyzer, "data_dir": data_dir}


def _save_and_analyze(analyzer_env, email_id, subject, from_addr, body, email_date):
    """Helper to save email, run analysis, return result."""
    store = analyzer_env["store"]
    analyzer = analyzer_env["analyzer"]

    store.save(
        email_id,
        email_date,
        {"Subject": subject, "From": from_addr},
        {"body_text": body}
    )

    result = analyzer.process_queue(lookback_days=7, limit=1, reference_date=REFERENCE_NOW)
    assert result["processed"] == 1, f"Expected 1 processed, got {result}"

    analysis = store.get_sidecar(email_id, "analysis.json")
    assert analysis is not None, f"Missing analysis for {email_id}"

    print(f"\nAnalysis for {email_id}:")
    print(json.dumps(analysis, indent=2))

    return analysis


def _assert_common(analysis, expected_rule_id, expected_action, input_from, input_subject):
    """Common assertions for all tests."""
    # Rule ID
    rule_id = analysis.get("original", {}).get("rule_id")
    assert rule_id == expected_rule_id, f"Expected rule {expected_rule_id}, got {rule_id}"

    # Action
    assert analysis.get("recommended_action") == expected_action, \
        f"Expected {expected_action}, got {analysis.get('recommended_action')}"

    # Original fields preserved
    assert analysis.get("original", {}).get("from") == input_from, \
        f"original.from should match input"
    assert analysis.get("original", {}).get("subject") == input_subject, \
        f"original.subject should match input"

    # Sender simplified (no @, reasonable length)
    sender = analysis.get("sender", "")
    assert "@" not in sender, f"Sender should not contain @: {sender}"
    assert len(sender) <= MAX_SENDER_LEN, \
        f"Sender too long ({len(sender)} > {MAX_SENDER_LEN}): {sender}"

    # Summary length
    summary = analysis.get("summary", "")
    assert len(summary) <= MAX_SUMMARY_LEN, \
        f"Summary too long ({len(summary)} > {MAX_SUMMARY_LEN}): {summary}"


class TestSchoolEmails:
    """Test school-related email rules."""

    def test_school_student_issue_gets_review(self, analyzer_env):
        """
        Email about specific child incident:
        - Vague subject, real info buried in body
        - Should extract child name + incident into summary
        - Rule: home-school-student → review
        """
        input_from = "Mrs. Johnson <sarah.johnson@springfield.k12.example.org>"
        input_subject = "Regarding class today"
        # Email from 2 hours ago (13:00) → display_date = " 1:00P"
        email_date = datetime(2026, 1, 21, 13, 0, 0)

        analysis = _save_and_analyze(
            analyzer_env,
            email_id="school_incident",
            subject=input_subject,
            from_addr=input_from,
            body="""Dear Parent,

I wanted to reach out about something that happened in class today. Johnny
was involved in a disagreement with another student during recess that
resulted in some pushing.

Johnny is fine and no one was hurt, but I wanted to make you aware and
discuss how we can work together to address this behavior.

Please call me at your earliest convenience so we can talk about next steps.

Best regards,
Mrs. Johnson
5th Grade Teacher
Springfield Elementary""",
            email_date=email_date
        )

        _assert_common(analysis, "home-school-student", "review", input_from, input_subject)

        # Summary should extract BURIED info, not echo vague subject
        summary = analysis.get("summary", "").lower()
        assert "johnny" in summary or "incident" in summary or "pushing" in summary, \
            f"Summary should extract buried info (johnny/incident), got: {summary}"
        assert summary != "regarding class today", \
            f"Summary should NOT just echo vague subject"

        # display_date: email at 13:00, now is 15:00 same day → " 1:00P"
        assert analysis.get("display_date") == " 1:00P"

    def test_school_general_newsletter_gets_archived(self, analyzer_env):
        """
        General school newsletter to all parents:
        - Rule: home-school-general → archive
        """
        input_from = "Springfield Elementary <newsletter@springfield.k12.example.org>"
        input_subject = "Weekly Update - Springfield Elementary"
        # Email from yesterday (Jan 20) → display_date = "Yester"
        email_date = datetime(2026, 1, 20, 10, 30, 0)

        analysis = _save_and_analyze(
            analyzer_env,
            email_id="school_newsletter",
            subject=input_subject,
            from_addr=input_from,
            body="""Dear Families,

Here's what's happening this week at Springfield Elementary!

CURRICULUM UPDATE:
- 5th grade is starting their fractions unit in math
- 3rd grade will begin their weather science project

UPCOMING EVENTS:
- Thursday: School picture day
- Friday: Early release at 1:30pm

LUNCH MENU:
Monday: Pizza, Tuesday: Tacos, Wednesday: Chicken nuggets

Have a great week!
Principal Martinez""",
            email_date=email_date
        )

        _assert_common(analysis, "home-school-general", "archive", input_from, input_subject)

        # display_date: email from yesterday → "Yester"
        assert analysis.get("display_date") == "Yester"


class TestMarketingEmails:
    """Test marketing/promotional email rules."""

    def test_marketing_promo_gets_archived(self, analyzer_env):
        """
        Marketing promotional email:
        - Rule: home-marketing-promo → archive
        """
        input_from = "Best Deals Store <deals@bestdeals.example.com>"
        input_subject = "🔥 FLASH SALE: 50% Off Everything!"
        # Email from 3 hours ago (12:00) → display_date = "12:00P"
        email_date = datetime(2026, 1, 21, 12, 0, 0)

        analysis = _save_and_analyze(
            analyzer_env,
            email_id="marketing_promo",
            subject=input_subject,
            from_addr=input_from,
            body="""LIMITED TIME OFFER!

Get 50% off EVERYTHING in our store!

Use code FLASH50 at checkout.

Sale ends midnight tonight - don't miss out!

Shop now: https://bestdeals.example.com

Unsubscribe: https://bestdeals.example.com/unsub""",
            email_date=email_date
        )

        _assert_common(analysis, "home-marketing-promo", "archive", input_from, input_subject)

        # display_date: email at 12:00, now is 15:00 same day → "12:00P"
        assert analysis.get("display_date") == "12:00P"


class TestReceiptEmails:
    """Test receipt/charge email field transformations."""

    def test_receipt_extracts_amount_and_simplifies_sender(self, analyzer_env):
        """
        Receipt email:
        - Dollar amount buried in body → extracted to summary
        - Sender simplified
        - Rule: home-routine-confirmation → archive
        """
        input_from = "Amazon.com <auto-confirm@amazon.example.com>"
        input_subject = "Your Amazon.com order of Anker USB-C Cable..."
        # Email from Sunday Jan 18, 2026 at 9:30 AM → display_date = "U 18JA"
        email_date = datetime(2026, 1, 18, 9, 30, 0)

        analysis = _save_and_analyze(
            analyzer_env,
            email_id="amazon_receipt",
            subject=input_subject,
            from_addr=input_from,
            body="""Hello,

Thank you for shopping with us. We'll send a confirmation when your item ships.

Order Details:
Anker USB-C to Lightning Cable, 6ft, MFi Certified
Quantity: 2
Price: $12.99 each

Order Total: $25.98
Shipping: FREE (Prime)

Track your package: https://amazon.example.com/orders/123

Thanks for being a Prime member!
Amazon.com""",
            email_date=email_date
        )

        _assert_common(analysis, "home-routine-confirmation", "archive", input_from, input_subject)

        # Sender should be simplified to just "Amazon"
        assert analysis.get("sender") == "Amazon"

        # Summary must contain dollar amount from body
        summary = analysis.get("summary", "")
        assert "$25" in summary or "$12.99" in summary, \
            f"Summary must contain dollar amount from body, got: {summary}"

        # display_date: email from Sunday Jan 18 → "U 18JA"
        assert analysis.get("display_date") == "U 18JA"

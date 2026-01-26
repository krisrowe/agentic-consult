"""Tests for process_list SDK method (on-demand email analysis).

NOTE: conftest.py auto-sets CONSULT_CONFIG_DIR for every test.
"""
import pytest
from datetime import datetime
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
    ref_date = datetime(2026, 1, 12, 12, 0, 0)
    return store, data_dir, ref_date


# --- process_list Tests ---

def test_with_single_msg_id(test_env):
    """Proof: process_list handles a single message ID."""
    store, data_dir, ref_date = test_env
    msg_id = "single-email"
    store.save(msg_id, ref_date, {"Subject": "Single", "From": "user@example.com"}, {
        "body_text": "Test content"
    })

    analyzer = EmailAnalyzer(store, provider=DummyProvider())
    results = analyzer.process_list([msg_id])

    assert len(results) == 1
    assert results[0]["id"] == msg_id
    assert results[0]["recommended_action"] == "review"
    # Verify sidecar was created
    assert store.has_sidecar(msg_id, "analysis.json")


def test_with_multi_msg_id(test_env):
    """Proof: process_list handles multiple message IDs."""
    store, data_dir, ref_date = test_env
    msg_ids = ["email-1", "email-2", "email-3"]

    for msg_id in msg_ids:
        store.save(msg_id, ref_date, {"Subject": f"Email {msg_id}", "From": "user@example.com"}, {
            "body_text": f"Content for {msg_id}"
        })

    analyzer = EmailAnalyzer(store, provider=DummyProvider())
    results = analyzer.process_list(msg_ids)

    assert len(results) == 3
    result_ids = [r["id"] for r in results]
    assert set(result_ids) == set(msg_ids)
    # Verify all sidecars were created
    for msg_id in msg_ids:
        assert store.has_sidecar(msg_id, "analysis.json")


def test_msg_id_not_found(test_env):
    """Proof: process_list returns error for missing message ID."""
    store, _, _ = test_env

    analyzer = EmailAnalyzer(store, provider=DummyProvider())
    results = analyzer.process_list(["nonexistent-id"])

    assert len(results) == 1
    assert results[0]["id"] == "nonexistent-id"
    assert "error" in results[0]


# --- Body Selection Tests ---

def test_uses_html_body_when_larger(test_env):
    """Proof: Analyzer uses HTML body when it's larger than text body.

    Bill statements often have financial data only in HTML while text is
    just a 'click here to view' placeholder.
    """
    store, _, ref_date = test_env
    msg_id = "html-rich"

    # HTML has the real content, text is just a placeholder
    html_body = "<html><body>Your statement balance is $123.45. Min payment: $25.00 due 02/13/2026.</body></html>"
    text_body = "Please visit our website to view your statement."

    store.save(msg_id, ref_date, {"Subject": "Statement", "From": "bank@example.com"}, {
        "body_html": html_body,
        "body_text": text_body
    })

    provider = PromptCapturingProvider()
    analyzer = EmailAnalyzer(store, provider=provider)
    analyzer.process_list([msg_id])

    assert len(provider.captured_prompts) == 1
    prompt = provider.captured_prompts[0]

    # HTML body should be in the prompt (it's larger and has the $ amounts)
    assert "$123.45" in prompt, "HTML body with financial data should be in prompt"
    assert "Min payment: $25.00" in prompt, "HTML body should contain min payment"


def test_uses_text_body_when_larger(test_env):
    """Proof: Analyzer uses text body when it's larger than HTML body."""
    store, _, ref_date = test_env
    msg_id = "text-rich"

    # Text has the content, HTML is minimal
    text_body = "Hello, this is a detailed plain text email with lots of important information about your account status and recent activity."
    html_body = "<p>Hi</p>"

    store.save(msg_id, ref_date, {"Subject": "Update", "From": "service@example.com"}, {
        "body_html": html_body,
        "body_text": text_body
    })

    provider = PromptCapturingProvider()
    analyzer = EmailAnalyzer(store, provider=provider)
    analyzer.process_list([msg_id])

    assert len(provider.captured_prompts) == 1
    prompt = provider.captured_prompts[0]

    # Text body should be in the prompt (it's larger)
    assert "detailed plain text email" in prompt, "Text body should be in prompt when larger"


def test_uses_snippet_when_no_body(test_env):
    """Proof: Analyzer falls back to snippet when both bodies are empty."""
    store, _, ref_date = test_env
    msg_id = "snippet-only"

    store.save(msg_id, ref_date, {"Subject": "Brief", "From": "alert@example.com"}, {
        "snippet": "Your package has been delivered to your front door."
    })

    provider = PromptCapturingProvider()
    analyzer = EmailAnalyzer(store, provider=provider)
    analyzer.process_list([msg_id])

    assert len(provider.captured_prompts) == 1
    prompt = provider.captured_prompts[0]

    # Snippet should be used as fallback
    assert "package has been delivered" in prompt, "Snippet should be used when no body"

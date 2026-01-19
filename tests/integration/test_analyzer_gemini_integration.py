import pytest
import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from email_archive import EmailStore
from agentic_consult.email.analyzer import EmailAnalyzer, GeminiProvider
from agentic_consult.config import load_main_config
from agentic_consult.cloud import get_cloud_provider

# INTEGRATION TEST: Calls real Gemini API using key from Vault.

def test_analyzer_with_real_gemini(tmp_path, monkeypatch):
    """
    End-to-End Proof: Brain discovers raw emails and saves real Gemini analysis.
    Key is pulled from GCP Secret Manager at runtime.
    """
    # 1. Resolve Project context
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or load_main_config().get("project_id")
    if not project_id:
        pytest.skip("Test Skipped: project_id not configured in local settings or environment.")

    # 2. Retrieve Secret from Vault
    provider = get_cloud_provider()
    api_key = provider.get_secret_value(project_id, "gemini-api-key")
    if not api_key:
        pytest.skip(f"Test Skipped: 'gemini-api-key' secret not found in project '{project_id}'. See README.md#cloud-deployment.")
    
    monkeypatch.setenv("GEMINI_API_KEY", api_key)

    # 3. Setup Isolated Data Environment
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("EMAIL_ARCHIVE_DATA_DIR", str(data_dir))
    
    store = EmailStore(data_dir)
    
    # 2. Prep Synthetic Emails (Rich content to give Gemini something to think about)
    emails = [
        {
            "id": "real_msg_001",
            "subj": "Lunch tomorrow?",
            "body": "Hey, are you free for lunch at 12:30 tomorrow at Joe's Pizza? Let me know!",
            "from": "test@example.com"
        },
        {
            "id": "real_msg_002",
            "subj": "[Marketing] Big Sale Event!",
            "body": "Unsubscribe from this newsletter. Check out our 50% off deals on all shoes today only!",
            "from": "sender@example.com"
        },
        {
            "id": "real_msg_003",
            "subj": "URGENT: Production Server Down",
            "body": "The main database is unresponsive. We need an immediate reboot of the us-central1 cluster.",
            "from": "test@fake.com"
        }
    ]
    
    for e in emails:
        store.save(e["id"], datetime.utcnow(), {"Subject": e["subj"], "From": e["from"]}, {"body_text": e["body"]})

    # 3. Initialize REAL Analyzer
    # Uses real GeminiProvider (default)
    analyzer = EmailAnalyzer(store)

    print("\n>> Running Real Gemini Analysis on 3 emails...")
    result = analyzer.process_queue(lookback_days=1, limit=3)
    
    # 4. Verifications
    assert result["processed"] == 3
    
    # Verify each email has a sidecar
    for e in emails:
        sidecar_path = data_dir / f"{store.list(limit=10)[0]['date'].strftime('%Y%m%d-%H%M%S')}_{e['id']}.analysis.json"
        # Since I can't guess the exact timestamp without listing, I'll use the SDK
        assert store.get_sidecar(e["id"], "analysis.json") is not None
        
        analysis = store.get_sidecar(e["id"], "analysis.json")
        print(f"   - {e['id']} Recommendation: {analysis.get('recommended_action')} ({analysis.get('reason')[:50]}...)")
        
        # Qualitative Checks (Checking that Gemini actually thought about the content)
        if e["id"] == "real_msg_002": # The marketing one
            assert analysis.get("recommended_action") in ["archive_now", "archive_later"]
        
        if e["id"] == "real_msg_003": # The urgent one
            assert analysis.get("recommended_action") in ["review", "track_as_task"]

    print("✅ INTEGRATION SUCCESS: Real Gemini analysis verified.")

import pytest
import json
from pathlib import Path
from datetime import datetime
from email_archive import EmailStore

# Sociable Unit Test for 'sidecar' capability.
# Verifies that processing outputs/status can be linked to emails.

def test_has_sidecar_generic(tmp_path):
    store = EmailStore(tmp_path)
    
    # 1. Setup email
    msg_id = "sidecar_test"
    date = datetime(2026, 1, 12, 15, 0, 0)
    store.save(msg_id, date, {"Subject": "Main"}, {"body": "Content"})
    
    # 2. Save a generic processing result
    processing_data = {
        "status": "processed",
        "worker_version": "1.0"
    }
    store.save_sidecar(msg_id, "processed.json", processing_data)
    
    # 3. Verify existence and content
    assert store.has_sidecar(msg_id, "processed.json")
    assert not store.has_sidecar(msg_id, "missing.json")
    
    loaded = store.get_sidecar(msg_id, "processed.json")
    assert loaded["status"] == "processed"

def test_get_sidecar_raw_text(tmp_path):
    store = EmailStore(tmp_path)
    msg_id = "text_test"
    store.save(msg_id, datetime.now(), {}, {})
    
    store.save_sidecar(msg_id, "tag.txt", "verified")
    
    # Verify file content is raw text
    assert store.get_sidecar(msg_id, "tag.txt") == "verified"

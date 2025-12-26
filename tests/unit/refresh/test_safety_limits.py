import tempfile
import json
import pytest
from pathlib import Path
from agentic_consult.cli.refresh import process_deltas

def test_safety_limit_exceeded():
    """Test that process_deltas aborts when expected_max_deltas is exceeded."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        deltas_path = tmp_path / 'deltas.json'
        
        # Create deltas with 2 items (1 create, 1 update)
        deltas = {
            "emails": [
                {
                    "id": "msg1",
                    "deltas": [
                        {"type": "task_create", "title": "Task 1"},
                        {"type": "task_update", "id": "1", "title": "Task 2"}
                    ]
                }
            ]
        }
        deltas_path.write_text(json.dumps(deltas))
        
        tasks = []
        
        # Run with limit 1 (should fail)
        with pytest.raises(SystemExit):
            process_deltas(deltas_path, {}, tmp_path, tasks, expected_max_deltas=1)

def test_safety_limit_respected():
    """Test that process_deltas proceeds when limit is respected."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        deltas_path = tmp_path / 'deltas.json'
        
        # Create deltas with 1 item
        deltas = {
            "emails": [
                {
                    "id": "msg1",
                    "deltas": [{"type": "task_create", "title": "Task 1"}]
                }
            ]
        }
        deltas_path.write_text(json.dumps(deltas))
        
        tasks = []
        
        # Run with limit 1 (should pass)
        # Note: process_deltas might try to run subprocess commands if not mocked/skipped.
        # We pass skip_task_writes=True in config to avoid side effects.
        process_deltas(deltas_path, {'skip_task_writes': True}, tmp_path, tasks, expected_max_deltas=1)

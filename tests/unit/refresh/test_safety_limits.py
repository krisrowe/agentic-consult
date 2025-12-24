import json
import tempfile
from pathlib import Path
from click.testing import CliRunner
from agentic_consult.cli.refresh import process_deltas

def test_safety_limit_exceeded():
    """Test that process_deltas aborts when expected_max_deltas is exceeded."""
    runner = CliRunner()
    
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        deltas_path = tmp_path / 'deltas.json'
        
        # Create deltas with 2 items (1 create, 1 update)
        deltas = {
            "tasks": {
                "create": [{"title": "Task 1"}],
                "update": [{"id": "1", "title": "Task 2"}]
            },
            "issues": {"update": []}
        }
        deltas_path.write_text(json.dumps(deltas))
        
        # Run with limit 1 (should fail)
        try:
            process_deltas(deltas_path, {}, tmp_path, expected_max_deltas=1)
            assert False, "Should have raised SystemExit"
        except SystemExit as e:
            assert e.code == 1

def test_safety_limit_respected():
    """Test that process_deltas proceeds when limit is respected."""
    runner = CliRunner()
    
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        deltas_path = tmp_path / 'deltas.json'
        
        # Create deltas with 1 item
        deltas = {
            "tasks": {
                "create": [{"title": "Task 1"}],
                "update": []
            },
            "issues": {"update": []}
        }
        deltas_path.write_text(json.dumps(deltas))
        
        # Run with limit 1 (should pass)
        # Note: process_deltas might try to run subprocess commands if not mocked/skipped.
        # We pass skip_task_writes=True in config to avoid side effects.
        process_deltas(deltas_path, {'skip_task_writes': True}, tmp_path, expected_max_deltas=1)

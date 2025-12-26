import tempfile
import json
import pytest
from pathlib import Path
from agentic_consult.cli.refresh import process_deltas

def test_delta_archiving():
    """Test that deltas.json is archived after processing."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        deltas_path = tmp_path / 'deltas.json'
        
        # Create deltas with 1 item
        deltas = {
            "emails": [
                {
                    "id": "msg1",
                    "deltas": [{"type": "task_create", "title": "Test Task"}]
                }
            ]
        }
        deltas_path.write_text(json.dumps(deltas))
        
        # Create dummy tasks list
        tasks = []
        
        # Process deltas (should archive)
        process_deltas(deltas_path, {}, tmp_path, tasks)
        
        # Check that deltas.json is gone (archived)
        assert not deltas_path.exists()
        
        # Check archive dir
        archive_dir = tmp_path / 'deltas_archive'
        assert archive_dir.exists()
        archived_files = list(archive_dir.glob('done_deltas_*.json'))
        assert len(archived_files) == 1

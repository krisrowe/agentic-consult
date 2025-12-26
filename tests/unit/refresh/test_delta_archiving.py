import tempfile
import json
import pytest
from pathlib import Path
from agentic_consult.cli.refresh import process_deltas

def test_delta_archiving():
    """Test that deltas.json is archived after processing when skip_task_writes is False."""
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
        
        # Run with skip_task_writes=False (should archive)
        # config is a dict
        process_deltas(deltas_path, {'skip_task_writes': False}, tmp_path, tasks)
        
        # Check that deltas.json is gone (archived)
        assert not deltas_path.exists()
        
        # Check archive dir
        archive_dir = tmp_path / 'deltas_archive'
        assert archive_dir.exists()
        archived_files = list(archive_dir.glob('done_deltas_*.json'))
        assert len(archived_files) == 1

def test_delta_not_archived_when_skipping():
    """Test that deltas.json is NOT archived when skip_task_writes is True."""
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
        
        tasks = []
        
        # Run with skip_task_writes=True (should NOT archive)
        process_deltas(deltas_path, {'skip_task_writes': True}, tmp_path, tasks)
        
        # Check that deltas.json still exists
        assert deltas_path.exists()
        
        # Check archive dir (should not exist or be empty)
        archive_dir = tmp_path / 'deltas_archive'
        if archive_dir.exists():
            assert not list(archive_dir.glob('done_deltas_*.json'))
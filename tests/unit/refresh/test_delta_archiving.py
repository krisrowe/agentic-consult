import json
import tempfile
from pathlib import Path
from agentic_consult.cli.refresh import process_deltas

def test_delta_archiving():
    """Test that deltas.json is archived after processing when skip_task_writes is False."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        deltas_path = tmp_path / 'deltas.json'
        
        # Create deltas with 1 item
        deltas = {
            "tasks": {
                "create": [{"title": "Test Task"}],
                "update": []
            },
            "issues": {"update": []}
        }
        deltas_path.write_text(json.dumps(deltas))
        
        # Run with skip_task_writes=False (should archive)
        process_deltas(deltas_path, {'skip_task_writes': False}, tmp_path)
        
        # Verify deltas.json was renamed
        assert not deltas_path.exists(), "deltas.json should have been renamed"
        
        # Verify archived file exists
        archived_files = list(tmp_path.glob("done_deltas_*.json"))
        assert len(archived_files) == 1, "Should have exactly one archived delta file"
        assert archived_files[0].name.startswith("done_deltas_"), "Archived file should have correct prefix"

def test_delta_not_archived_when_skipping():
    """Test that deltas.json is NOT archived when skip_task_writes is True."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        deltas_path = tmp_path / 'deltas.json'
        
        # Create deltas with 1 item
        deltas = {
            "tasks": {
                "create": [{"title": "Test Task"}],
                "update": []
            },
            "issues": {"update": []}
        }
        deltas_path.write_text(json.dumps(deltas))
        
        # Run with skip_task_writes=True (should NOT archive)
        process_deltas(deltas_path, {'skip_task_writes': True}, tmp_path)
        
        # Verify deltas.json still exists
        assert deltas_path.exists(), "deltas.json should still exist when skipping writes"
        
        # Verify no archived files
        archived_files = list(tmp_path.glob("done_deltas_*.json"))
        assert len(archived_files) == 0, "Should have no archived files when skipping writes"

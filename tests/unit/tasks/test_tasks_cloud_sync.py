import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from agentic_consult.cli.refresh import process_deltas
from agentic_consult.tasks import load_tasks, save_tasks
from agentic_consult.tasks.providers import TaskProvider

def test_create_and_update_sync_logic(tmp_path):
    """
    Verifies that processing deltas correctly updates local state,
    and then a subsequent sync operation invokes the provider correctly.
    """
    customer_dir = tmp_path / "customer"
    customer_dir.mkdir()
    
    # 1. Setup Initial Local State
    initial_tasks = [
        {
            "sequence_number": 1,
            "title": "Task 1",
            "provider_id": "remote_task_1",
            "is_dirty": False,
            "status": 0
        },
        {
            "sequence_number": 2,
            "title": "Task 2",
            "provider_id": "remote_task_2", 
            "is_dirty": False,
            "status": 0
        }
    ]

    # 2. Create Deltas (1 Create, 2 Updates)
    deltas = {
        "emails": [
            {
                "id": "email1",
                "deltas": [
                    {"type": "task_create", "title": "Task 3", "content": "New Content"},
                    {"type": "task_update", "id": "1", "content": "Updated Content 1"},
                    {"type": "task_update", "id": "2", "content": "Updated Content 2"}
                ]
            }
        ]
    }
    
    # Save initial tasks
    save_tasks(customer_dir, initial_tasks)
    
    # Save deltas
    deltas_path = customer_dir / "deltas.json"
    deltas_path.write_text(json.dumps(deltas))
    
    # 3. Run Process Deltas (Local Updates Only)
    tasks = load_tasks(customer_dir)
    process_deltas(deltas_path, {}, customer_dir, tasks)
    
    # Assert Local State AFTER process_deltas
    updated_tasks = load_tasks(customer_dir)
    assert len(updated_tasks) == 3
    
    # 4. Setup Mock Provider for Sync Test
    from agentic_consult.tasks.providers.ticktick import TicktickProvider
    provider = TicktickProvider()
    
    # Mock the low-level methods
    provider.create_task = MagicMock(return_value="remote_Task 3")
    provider.update_task = MagicMock(return_value=True)
    provider._fetch_remote_tasks = MagicMock(return_value=[]) # No new remote tasks
    
    # 5. Run Sync
    provider.sync(updated_tasks)
    
    # 6. Assertions
    
    # Assert create_task called once for Task 3
    provider.create_task.assert_called_once()
    args, _ = provider.create_task.call_args
    assert args[0]['title'] == "Task 3"
    
    # Assert update_task called twice (Task 1 and Task 2)
    assert provider.update_task.call_count == 2
    
    # Verify calls
    calls = provider.update_task.call_args_list
    ids_updated = sorted([c.args[0] for c in calls])
    assert ids_updated == ["remote_task_1", "remote_task_2"]
    
    # Verify Task 3 got its remote ID assigned in memory
    t3_synced = next(t for t in updated_tasks if t['sequence_number'] == 3)
    assert t3_synced['provider_id'] == "remote_Task 3"
    assert t3_synced['is_dirty'] is False
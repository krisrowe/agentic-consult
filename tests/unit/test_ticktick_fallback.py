import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from agentic_consult.ticktick import fetch_and_cache_tasks

def test_ticktick_fallback_to_cache():
    """Test that fetch_and_cache_tasks falls back to local cache if fetching fails."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        customer_dir = tmp_path / "fakecorp"
        customer_dir.mkdir()
        tasks_dir = customer_dir / "tasks"
        tasks_dir.mkdir()
        
        # Create a cached tasks.json
        cached_tasks = [{"id": "cached1", "title": "Cached Task"}]
        with open(tasks_dir / "tasks.json", "w") as f:
            json.dump(cached_tasks, f)
            
        customer = {"name": "FakeCorp", "slug": "fakecorp"}
        
        # Mock fetch_tasks to return empty list (simulating failure or no new tasks)
        with patch("agentic_consult.ticktick.fetch_tasks") as mock_fetch:
            mock_fetch.return_value = []
            
            # Should return 1 (from cache)
            count = fetch_and_cache_tasks(customer, customer_dir)
            
            assert count == 1
            mock_fetch.assert_called_once()

def test_ticktick_no_cache_no_fetch():
    """Test when both fetch and cache are empty."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        customer_dir = tmp_path / "fakecorp"
        customer_dir.mkdir()
        
        customer = {"name": "FakeCorp", "slug": "fakecorp"}
        
        with patch("agentic_consult.ticktick.fetch_tasks") as mock_fetch:
            mock_fetch.return_value = []
            
            count = fetch_and_cache_tasks(customer, customer_dir)
            
            assert count == 0

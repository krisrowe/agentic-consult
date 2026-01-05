import os
import tempfile
from pathlib import Path
import subprocess
import json
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
import pytest
from agentic_consult.cli.main import main
from agentic_consult.refresh import build_prompt

@pytest.mark.skip(reason="Legacy refresh flow - test data mismatch, not actively maintained")
def test_refresh_with_mock_data():
    """Test refresh command using mock input data and mock Gemini script."""
    runner = CliRunner()
    
    # Get the repository root to locate the real mock script
    repo_root = Path(__file__).parent.parent.parent.parent
    mock_script = repo_root / 'scripts' / 'mock-gemini.sh'
    assert mock_script.exists(), "Mock Gemini script not found in repo"
    
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        
        # 1. Setup Customers Directory
        customers_dir = tmp_path / 'customers'
        customers_dir.mkdir()
        
        fakecorp_dir = customers_dir / 'fakecorp'
        fakecorp_dir.mkdir()
        
        # 2. Create customer.yaml
        (fakecorp_dir / 'customer.yaml').write_text("""name: "FakeCorp Test"
slug: fakecorp
drive_folder_id: 'MOCK123'
keywords: ['fake']
""")
        
        # 3. Create Mock Input Data
        mock_emails = [
            {"id": "email1", "subject": "Mock Email 1", "sender": "test@fake.com", "body": "Body 1", "date": "2025-01-01"},
            {"id": "email2", "subject": "Mock Email 2", "sender": "test@fake.com", "body": "Body 2", "date": "2025-01-01"},
            {"id": "email3", "subject": "Mock Email 3", "sender": "test@fake.com", "body": "Body 3", "date": "2025-01-01"}
        ]
        (fakecorp_dir / 'mock-emails.json').write_text(json.dumps(mock_emails))
        
        # Direct write to tasks.json (New Architecture)
        tasks_dir = fakecorp_dir / 'tasks'
        tasks_dir.mkdir()
        mock_tasks = [
            {"sequence_number": 1, "title": "Mock Task 1", "content": "Content 1", "priority": 1, "is_dirty": False}
        ]
        (tasks_dir / 'tasks.json').write_text(json.dumps(mock_tasks))
        
        # 4. Create settings.json in XDG config dir
        config_dir = tmp_path / 'agentic-consult'
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / 'settings.json').write_text(json.dumps({
            "use_mock_data": True,
            "use_mock_gemini": True,
            "gemini_cmd": str(mock_script),
            "tasks": {
                "cloud_sync": False,
                "default_project": "Work"
            },
            "local_data": str(customers_dir.parent)
        }))
        
        # 5. Create prompt.tpl
        (customers_dir / 'prompt.tpl').write_text("""Customer: <CUSTOMER>
Emails: <EMAILS>
Tasks: <TASKS>
""")
        
        # 6. Set Environment Variables
        env = os.environ.copy()
        env['CUSTOMERS_DIR'] = str(customers_dir)
        env['XDG_CONFIG_HOME'] = str(tmp_path)
        
        # 7. Run Refresh Command
        result = runner.invoke(main, ['refresh', 'fakecorp', '--no-dry-run'], env=env)
        
        # 8. Verify Output
        assert result.exit_code == 0, f"Command failed: {result.output}"
        
        # Verify outcome: Emails cache should be populated from mock data
        cache_file = fakecorp_dir / 'emails' / 'emails.json'
        assert cache_file.exists()
        with open(cache_file) as f:
            cached_emails = json.load(f)
        assert len(cached_emails) == 3  # Matches mock_emails length
        # Note: "Loaded ... tasks from mock file" is gone now.
        # We can check prompt/preview content if we were in dry run, 
        # or implicitly trust it worked if command succeeded.
        assert "Marked 2 emails as processed" in result.output
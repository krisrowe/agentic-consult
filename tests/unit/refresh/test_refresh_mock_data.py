import os
import json
import tempfile
from pathlib import Path
from click.testing import CliRunner
from agentic_consult.cli.main import main

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
        
        mock_tasks = [
            {"title": "Mock Task 1", "content": "Content 1", "priority": 1}
        ]
        (fakecorp_dir / 'mock-server-tasks.json').write_text(json.dumps(mock_tasks))
        
        # 4. Create config.yaml in customers root
        # Point gemini_cmd to the real mock script
        (customers_dir / 'config.yaml').write_text(f"""
use_mock_data: true
use_mock_gemini: true
gemini_cmd: {mock_script}
skip_task_writes: true
ticktick_project: Work
customers_local_path: {customers_dir}
""")

        # 5. Create prompt.tpl in repo root (cli.py fallback) OR customers root
        # Let's put it in customers root to test override/lookup
        (customers_dir / 'prompt.tpl').write_text("""Customer: <CUSTOMER>
Emails: <EMAILS>
Tasks: <TASKS>
""")

        # 6. Set Environment Variables
        env = os.environ.copy()
        # We don't strictly need CUSTOMERS_DIR if we pass it in config, 
        # but cli.py logic for finding config.yaml relies on get_active_customers_root.
        # get_active_customers_root checks CUSTOMERS_DIR first.
        env['CUSTOMERS_DIR'] = str(customers_dir)
        env['XDG_CONFIG_HOME'] = str(tmp_path)
        
        # 7. Run Refresh Command
        result = runner.invoke(main, ['refresh', 'fakecorp', '--no-dry-run'], env=env)
        # 8. Verify Output
        print(result.output) # For debugging if test fails
        assert result.exit_code == 0
        
        # Verify mock data usage
        assert "Using mock emails from" in result.output
        assert "Using mock tasks from" in result.output
        
        # Verify deltas.json generation (Mock Gemini script generates this)
        deltas_path = fakecorp_dir / 'deltas.json'
        # Since skip_task_writes is True, it should NOT be archived
        assert deltas_path.exists(), "deltas.json should still exist because skip_task_writes is True"
        
        # Verify processing state
        processed_file = fakecorp_dir / 'emails_processed.txt'
        assert processed_file.exists()
        processed_content = processed_file.read_text()
        assert "email1" in processed_content
        assert "email2" in processed_content
        assert "email3" not in processed_content, "email3 should not be processed as it wasn't in mock-deltas.json"
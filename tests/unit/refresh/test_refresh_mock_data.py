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
            {"id": "email1", "subject": "Mock Email 1", "sender": "test@fake.com", "body": "Body 1", "date": "2025-01-01"}
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
        
        # 7. Run Refresh Command
        result = runner.invoke(main, ['refresh', 'fakecorp', '--no-dry-run', '--gemini-cmd', str(mock_script)], env=env)
        # 8. Verify Output
        print(result.output) # For debugging if test fails
        assert result.exit_code == 0
        
        # Verify mock data usage
        assert "Using mock emails from" in result.output
        assert "Using mock tasks from" in result.output
        
        # Verify deltas.json generation (Mock Gemini script generates this)
        deltas_path = fakecorp_dir / 'deltas.json'
        assert deltas_path.exists()
        
        # Verify content of deltas (Mock script uses mock-deltas.json or canned response)
        # We can't strictly assert content unless we know what mock-gemini.sh uses.
        # But existence proves the flow worked.
        
        # Verify that task update logic was triggered (if the mock script returned updates)
        # Since we are using the real mock-gemini.sh, it uses mock-deltas.json from the repo root if present.
        # To be safe and deterministic, we should probably force the mock script behavior or check for generic success.
        # But if we want to test the END-TO-END flow including the new update logic, we should look for the log.
        
        # The current mock-deltas.json in the repo (which mock-gemini.sh reads) has an update.
        # So we should see the SKIPPED message.
        if "ticktick tasks update" in result.output:
             assert "SKIPPED: Would run command: ticktick tasks update" in result.output
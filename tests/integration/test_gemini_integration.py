import os
import json
import sys
import pytest
import subprocess
from pathlib import Path
from click.testing import CliRunner
from agentic_consult.cli import main

@pytest.mark.integration
def test_gemini_integration_real_model():
    """
    Integration test using the REAL Gemini model with MOCK data.
    Verifies that the prompt engineering correctly translates mock emails/tasks
    into expected deltas (Create/Update actions).
    """
    runner = CliRunner()
    
    with runner.isolated_filesystem() as tmp_dir:
        tmp_path = Path(tmp_dir)
        customers_dir = tmp_path / 'customers'
        customers_dir.mkdir()
        
        gemini_test_dir = customers_dir / 'gemini_test'
        gemini_test_dir.mkdir()
        
        # 1. Setup Mock Data
        # Tasks: 3 pre-existing tasks
        mock_tasks = [
            {"id": "task_1", "title": "Prepare Q3 Report", "content": "Draft the financial summary.", "priority": 3, "status": 0},
            {"id": "task_2", "title": "Buy Groceries", "content": "Milk, eggs, bread.", "priority": 1, "status": 0},
            {"id": "task_3", "title": "Schedule Dentist", "content": "Routine checkup.", "priority": 1, "status": 0}
        ]
        (gemini_test_dir / 'mock-server-tasks.json').write_text(json.dumps(mock_tasks))
        
        # Emails: Triggers for Update and Create
        mock_emails = [
            {
                "subject": "Re: Q3 Report",
                "sender": "boss@fakecorp.com",
                "body": "Please rename the Q3 report task to 'Q3 Financial Analysis' and bump priority to high.",
                "date": "2025-01-01"
            },
            {
                "subject": "New Project Alpha",
                "sender": "pm@fakecorp.com",
                "body": "We need to start Project Alpha. Please create a task for 'Project Alpha Kickoff' with high priority.",
                "date": "2025-01-02"
            }
        ]
        (gemini_test_dir / 'mock-emails.json').write_text(json.dumps(mock_emails))
        
        # Customer Config
        (gemini_test_dir / 'customer.yaml').write_text("""name: "Gemini Integration Test"
slug: gemini_test
drive_folder_id: "MOCK_DRIVE_ID"
keywords: ["gemini"]
""")
        
        # Global Config
        (customers_dir / 'config.yaml').write_text(f"""
use_mock_data: true
use_mock_gemini: false
skip_task_writes: true
ticktick_project: Work
customers_local_path: {customers_dir}
gemini:
  debug: true
""")
        
        # 2. Run Consult Refresh
        # Calculate repo root (where agentic_consult package is)
        repo_root = Path(__file__).resolve().parent.parent.parent
        
        env = os.environ.copy()
        env['CUSTOMERS_DIR'] = str(customers_dir)
        env['LOG_LEVEL'] = 'DEBUG'
        env['PYTHONPATH'] = str(repo_root)
        # Ensure we use the venv python
        python_cmd = sys.executable
        
        # Use subprocess to run the module to ensure we capture logs properly
        cmd = [python_cmd, '-m', 'agentic_consult', 'customers', 'refresh', 'gemini_test', '--no-dry-run']
        
        print(f"DEBUG: python_cmd={python_cmd}")
        print(f"DEBUG: cwd={os.getcwd()}")
        print(f"DEBUG: PYTHONPATH={env.get('PYTHONPATH')}")
        
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        
        # 3. Verify Execution
        print(result.stdout)
        print(result.stderr)
        assert result.returncode == 0
        
        # Combine stdout and stderr for checking
        output = result.stdout + result.stderr
        
        # Verify Real Gemini Invocation (via log message in stderr)
        assert "Calling Gemini command" in output
        assert "mock-gemini.sh" not in output
        
        # Verify Detailed Plan Reporting
        assert "=== Proposed Plan (deltas.json) ===" in output
        
        # 4. Verify Deltas Content
        deltas_path = gemini_test_dir / 'deltas.json'
        assert deltas_path.exists(), "deltas.json was not generated"
        
        with open(deltas_path, 'r') as f:
            data = json.load(f)
            
        tasks = data.get('tasks', {})
        creates = tasks.get('create', [])
        updates = tasks.get('update', [])
        
        # Check Create: 'Project Alpha Kickoff'
        found_create = any('Project Alpha Kickoff' in t.get('title', '') for t in creates)
        assert found_create, "Did not find expected task creation for 'Project Alpha Kickoff'"
        
        # Check Update: 'task_1' -> 'Q3 Financial Analysis'
        found_update = False
        for t in updates:
            if t.get('id') == 'task_1' and 'Q3 Financial Analysis' in t.get('title', ''):
                found_update = True
                break
        assert found_update, "Did not find expected task update for 'Q3 Financial Analysis' on task_1"

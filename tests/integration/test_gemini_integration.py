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
        
        # Emails: Triggers for Update, Create, and Ignore
        mock_emails = [
            {
                "id": "email_update",
                "subject": "Re: Q3 Report",
                "sender": "boss@fakecorp.com",
                "body": "Please rename the Q3 report task to 'Q3 Financial Analysis' and bump priority to high.",
                "date": "2025-01-01"
            },
            {
                "id": "email_create",
                "subject": "New Project Alpha",
                "sender": "pm@fakecorp.com",
                "body": "We need to start Project Alpha. Please create a task for 'Project Alpha Kickoff' with high priority.",
                "date": "2025-01-02"
            },
            {
                "id": "email_ignore",
                "subject": "Automatic Reply: Out of Office",
                "sender": "boss@fakecorp.com",
                "body": "I am out of the office until next week. For urgent matters, contact support.",
                "date": "2025-01-03"
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
  debug: false
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
        
        # Use subprocess to run the module and stream output
        # Note: 'refresh' is a top-level command, not under 'customers'
        cmd = [python_cmd, '-m', 'agentic_consult', 'refresh', 'gemini_test', '--no-dry-run']
        
        print(f"DEBUG: python_cmd={python_cmd}")
        print(f"DEBUG: cwd={os.getcwd()}")
        print(f"DEBUG: PYTHONPATH={env.get('PYTHONPATH')}")
        print(f"DEBUG: Executing command: {' '.join(cmd)}")
        
        # Use Popen to stream output
        process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1  # Line buffered
        )
        
        stdout_captured = []
        stderr_captured = []
        
        import select
        
        while True:
            reads = [process.stdout.fileno(), process.stderr.fileno()]
            ret = select.select(reads, [], [])
            
            for fd in ret[0]:
                if fd == process.stdout.fileno():
                    line = process.stdout.readline()
                    if line:
                        sys.stdout.write(line)
                        stdout_captured.append(line)
                if fd == process.stderr.fileno():
                    line = process.stderr.readline()
                    if line:
                        sys.stderr.write(line)
                        stderr_captured.append(line)
            
            if process.poll() is not None:
                # Process ended, read remaining
                for line in process.stdout:
                    sys.stdout.write(line)
                    stdout_captured.append(line)
                for line in process.stderr:
                    sys.stderr.write(line)
                    stderr_captured.append(line)
                break

        returncode = process.returncode
        output = "".join(stdout_captured) + "".join(stderr_captured)
        
        # 3. Verify Execution
        assert returncode == 0
        
        # Verify Real Gemini Invocation (via log message in stderr)
        assert "Calling Gemini command" in output or "Executing Gemini" in output
        assert "mock-gemini.sh" not in output
        
        # Verify Detailed Plan Reporting
        assert "=== Proposed Plan (deltas.json) ===" in output
        
        # 4. Verify Deltas Content
        deltas_path = gemini_test_dir / 'deltas.json'
        # Note: If skip_task_writes is True, deltas.json is NOT archived, so it should exist
        assert deltas_path.exists(), "deltas.json was not generated or was archived unexpectedly"
        
        from agentic_consult.utils import clean_json_output
        with open(deltas_path, 'r') as f:
            data = json.loads(clean_json_output(f.read()))
            
        emails = data.get('emails', [])
        assert emails, "No emails found in response"
        
        # Helper to find email entry by ID
        def get_email_entry(eid):
            for e in emails:
                if e.get('id') == eid:
                    return e
            return None

        # Check Create: 'Project Alpha Kickoff' (email_create)
        email_create_entry = get_email_entry("email_create")
        assert email_create_entry, "Missing entry for email_create"
        found_create = any('Project Alpha Kickoff' in d.get('title', '') for d in email_create_entry.get('deltas', []) if d.get('type') == 'task_create')
        assert found_create, "Did not find expected task creation for 'Project Alpha Kickoff'"
        
        # Check Update: 'task_1' -> 'Q3 Financial Analysis' (email_update)
        email_update_entry = get_email_entry("email_update")
        assert email_update_entry, "Missing entry for email_update"
        found_update = False
        for d in email_update_entry.get('deltas', []):
            if d.get('type') == 'task_update' and d.get('id') == 'task_1' and 'Q3 Financial Analysis' in d.get('title', ''):
                found_update = True
                break
        assert found_update, "Did not find expected task update for 'Q3 Financial Analysis' on task_1"

        # Check Ignore: Automatic Reply (email_ignore)
        email_ignore_entry = get_email_entry("email_ignore")
        assert email_ignore_entry, "Missing entry for email_ignore"
        ignore_data = email_ignore_entry.get('ignore', {})
        assert ignore_data, "email_ignore should have an 'ignore' object"
        # We expect it to likely be 'informational' or 'other' or 'out_of_scope'
        # checking specifically that it IS ignored is the key
        assert 'reason' in ignore_data

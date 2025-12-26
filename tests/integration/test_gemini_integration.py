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
        # Tasks: 3 pre-existing tasks in local tasks.json format
        tasks_dir = gemini_test_dir / 'tasks'
        tasks_dir.mkdir()
        
        # Note: We use sequence_number as ID now
        mock_tasks = [
            {
                "sequence_number": 1,
                "title": "Prepare Q3 Report",
                "content": "Draft the financial summary.",
                "priority": 3,
                "status": 0,
                "is_dirty": False,
                "provider_id": "task_1"
            },
            {
                "sequence_number": 2,
                "title": "Buy Groceries",
                "content": "Milk, eggs, bread.",
                "priority": 1,
                "status": 0,
                "is_dirty": False,
                "provider_id": "task_2"
            },
            {
                "sequence_number": 3,
                "title": "Schedule Dentist",
                "content": "Routine checkup.",
                "priority": 1,
                "status": 0,
                "is_dirty": False,
                "provider_id": "task_3"
            }
        ]
        (tasks_dir / 'tasks.json').write_text(json.dumps(mock_tasks))
        
        # Emails: Triggers for Update, Create, and Ignore
        mock_emails = [
            {
                "id": "email_update",
                "subject": "Re: Q3 Report",
                "sender": "boss@gemini-test.com",
                "body": "Please rename the Q3 report task to 'Q3 Financial Analysis' and bump priority to high.",
                "date": "2025-01-01"
            },
            {
                "id": "email_create",
                "subject": "New Project Alpha",
                "sender": "pm@gemini-test.com",
                "body": "We need to start Project Alpha. Please create a task for 'Project Alpha Kickoff' with high priority.",
                "date": "2025-01-02"
            },
            {
                "id": "email_ignore",
                "subject": "Automatic Reply: Out of Office",
                "sender": "boss@gemini-test.com",
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
        # sync_tasks: false to avoid provider calls
        (customers_dir / 'config.yaml').write_text(f"""
use_mock_data: true
use_mock_gemini: false
skip_task_writes: false
sync_tasks: false
ticktick_project: Work
customers_local_path: {customers_dir}
gemini:
  debug: false
""")
        
        # 2. Run Consult Refresh
        repo_root = Path(__file__).resolve().parent.parent.parent
        
        env = os.environ.copy()
        env['CUSTOMERS_DIR'] = str(customers_dir)
        env['LOG_LEVEL'] = 'DEBUG'
        env['PYTHONPATH'] = str(repo_root)
        python_cmd = sys.executable
        
        cmd = [python_cmd, '-m', 'agentic_consult', 'refresh', 'gemini_test', '--no-dry-run']
        
        print(f"DEBUG: Executing command: {' '.join(cmd)}")
        
        process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
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
                for line in process.stdout:
                    sys.stdout.write(line)
                    stdout_captured.append(line)
                for line in process.stderr:
                    sys.stderr.write(line)
                    stderr_captured.append(line)
                break

        returncode = process.returncode
        output = "".join(stdout_captured) + "".join(stderr_captured)
        
        assert returncode == 0
        
        # 4. Verify Deltas Content
        deltas_path = gemini_test_dir / 'deltas.json'
        # Since we ran with skip_task_writes: false (so local updates happen),
        # but we mock the provider/sync, the deltas might be archived?
        # Refresh logic: "12. Process Deltas (Updates Local State)" -> "Archive the Delta File"
        # So deltas.json will be moved to archive.
        # We need to find the archived file or check local state changes.
        
        # Let's check local tasks.json for updates
        with open(tasks_dir / 'tasks.json') as f:
            updated_tasks = json.load(f)
            
        # Check Create: 'Project Alpha Kickoff'
        created_task = next((t for t in updated_tasks if 'Project Alpha Kickoff' in t['title']), None)
        assert created_task, "Did not find created task 'Project Alpha Kickoff' in local tasks.json"
        assert created_task['is_dirty'] is True
        
        # Check Update: 'task_1' -> 'Q3 Financial Analysis'
        # task_1 had sequence_number 1
        updated_task_1 = next((t for t in updated_tasks if t['sequence_number'] == 1), None)
        assert updated_task_1, "Task #1 missing"
        assert 'Q3 Financial Analysis' in updated_task_1['title'], "Task #1 title not updated"
        assert updated_task_1['is_dirty'] is True
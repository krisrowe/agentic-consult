import tempfile
import json
import subprocess
from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner
from agentic_consult.cli.main import main
from agentic_consult.processing_state import load_processed_emails


def test_end_to_end_email_processing_tracking():
    """
    End-to-end test: Run refresh command with mock Gemini and verify emails_processed.txt is created.
    Uses mock Gemini, mock data, skip fetch, and mocked subprocess to avoid network I/O.
    """
    runner = CliRunner()
    
    with runner.isolated_filesystem() as tmp_dir:
        tmp_path = Path(tmp_dir)
        customers_dir = tmp_path / 'customers'
        customers_dir.mkdir()
        
        test_customer_dir = customers_dir / 'testcorp'
        test_customer_dir.mkdir()
        
        # Setup customer config
        (test_customer_dir / 'customer.yaml').write_text("""name: "Test Corp"
slug: testcorp
drive_folder_id: "test123"
keywords: ["testcorp"]
""")
        
        # Setup mock emails
        emails_dir = test_customer_dir / 'emails'
        emails_dir.mkdir()
        mock_emails = [
            {"id": "email1", "subject": "Test 1", "from": "test@testcorp.com", "body": "Test email 1"},
            {"id": "email2", "subject": "Test 2", "from": "test@testcorp.com", "body": "Test email 2"},
            {"id": "email3", "subject": "Test 3", "from": "test@testcorp.com", "body": "Test email 3"},
        ]
        (emails_dir / 'emails.json').write_text(json.dumps(mock_emails))
        
        # Setup mock tasks
        tasks_dir = test_customer_dir / 'tasks'
        tasks_dir.mkdir()
        (tasks_dir / 'tasks.json').write_text(json.dumps([]))
        
        # Setup config with mock Gemini
        (customers_dir / 'config.yaml').write_text("""use_mock_gemini: true
use_mock_data: true
skip_task_writes: false
ticktick_project: Work
""")

        # Create prompt.tpl in the XDG config home (tmp_path is set as XDG_CONFIG_HOME)
        config_dir_for_prompt = tmp_path / 'agentic-consult'
        config_dir_for_prompt.mkdir(parents=True, exist_ok=True)
        (config_dir_for_prompt / 'prompt.tpl').write_text("""Customer: <CUSTOMER>
Emails: <EMAILS>
Tasks: <TASKS>
""")
        
        # Setup mock Gemini script response
        repo_root = Path(__file__).parent.parent.parent.parent
        mock_deltas = {
            "tasks": {
                "create": [
                    {"title": "Task from email1", "priority": 1, "content": "Test", "email_id": "email1"}
                ],
                "update": []
            },
            "ignoring": [
                {"email_id": "email2", "disposition": "informational", "reason": "No action needed"},
                {"email_id": "email3", "disposition": "informational", "reason": "No action needed"}
            ],
            "issues": {"update": []}
        }
        (repo_root / 'mock-deltas.json').write_text(json.dumps(mock_deltas))
        
        # Mock subprocess.run to avoid actual ticktick CLI calls
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(mock_deltas), stderr='')
            
            env = {'CUSTOMERS_DIR': str(customers_dir)}
            result = runner.invoke(
                main,
                ['refresh', 'testcorp', '--no-dry-run', '--skip-fetch'],
                env=env
            )
            
            # Verify command succeeded
            assert result.exit_code == 0, f"Command failed: {result.output}"
            
            # Verify emails_processed.txt was created with all email IDs
            processed_emails = load_processed_emails(test_customer_dir)
            assert processed_emails == {"email1", "email2", "email3"}, \
                f"Expected all 3 emails to be marked as processed, got: {processed_emails}"
            
            # Verify the file exists and has correct content
            processed_file = test_customer_dir / 'emails_processed.txt'
            assert processed_file.exists(), "emails_processed.txt should exist"
            
            with open(processed_file, 'r') as f:
                lines = [line.strip() for line in f if line.strip()]
            assert set(lines) == {"email1", "email2", "email3"}


def test_end_to_end_skip_processed_emails_on_rerun():
    """
    End-to-end test: Run refresh twice and verify second run skips already-processed emails.
    """
    runner = CliRunner()
    
    with runner.isolated_filesystem() as tmp_dir:
        tmp_path = Path(tmp_dir)
        customers_dir = tmp_path / 'customers'
        customers_dir.mkdir()
        
        test_customer_dir = customers_dir / 'testcorp'
        test_customer_dir.mkdir()
        
        # Setup customer config
        (test_customer_dir / 'customer.yaml').write_text("""name: "Test Corp"
slug: testcorp
drive_folder_id: "test123"
""" )
        
        # Setup mock emails
        emails_dir = test_customer_dir / 'emails'
        emails_dir.mkdir()
        mock_emails = [
            {"id": "email1", "subject": "Test 1", "from": "test@testcorp.com"},
            {"id": "email2", "subject": "Test 2", "from": "test@testcorp.com"},
        ]
        (emails_dir / 'emails.json').write_text(json.dumps(mock_emails))
        
        # Setup mock tasks
        tasks_dir = test_customer_dir / 'tasks'
        tasks_dir.mkdir()
        (tasks_dir / 'tasks.json').write_text(json.dumps([]))
        
        # Setup config
        (customers_dir / 'config.yaml').write_text("""use_mock_gemini: true
use_mock_data: true
skip_task_writes: false
""")

        # Create prompt.tpl in the XDG config home (tmp_path is set as XDG_CONFIG_HOME)
        config_dir_for_prompt = tmp_path / 'agentic-consult'
        config_dir_for_prompt.mkdir(parents=True, exist_ok=True)
        (config_dir_for_prompt / 'prompt.tpl').write_text("""Customer: <CUSTOMER>
Emails: <EMAILS>
Tasks: <TASKS>
""")
        
        # Setup mock Gemini response
        repo_root = Path(__file__).parent.parent.parent.parent
        mock_deltas = {
            "tasks": {"create": [], "update": []},
            "ignoring": [
                {"email_id": "email1", "disposition": "informational", "reason": "No action needed"},
                {"email_id": "email2", "disposition": "informational", "reason": "No action needed"}
            ],
            "issues": {"update": []}
        }
        (repo_root / 'mock-deltas.json').write_text(json.dumps(mock_deltas))
        
        # Mock subprocess
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(mock_deltas), stderr='')
            
            env = {'CUSTOMERS_DIR': str(customers_dir)}
            
            # First run - should process both emails
            result1 = runner.invoke(
                main,
                ['refresh', 'testcorp', '--no-dry-run', '--skip-fetch'],
                env=env
            )
            assert result1.exit_code == 0
            
            # Verify both emails were marked as processed
            processed = load_processed_emails(test_customer_dir)
            assert processed == {"email1", "email2"}
            
            # Second run - should skip both emails
            # Reset emails.json to original state
            (emails_dir / 'emails.json').write_text(json.dumps(mock_emails))
            
            result2 = runner.invoke(
                main,
                ['refresh', 'testcorp', '--no-dry-run', '--skip-fetch'],
                env=env,
                catch_exceptions=False
            )
            
            # Should succeed but skip all emails
            assert result2.exit_code == 0
            
            # Verify emails.json was filtered to empty list
            with open(emails_dir / 'emails.json', 'r') as f:
                filtered_emails = json.load(f)
            assert filtered_emails == [], "All emails should have been filtered out on second run"


def test_local_emails_already_processed_are_skipped():
    """
    Permutation 1: Local emails.json + already processed → Skip
    Verify that emails in local emails.json that are already in emails_processed.txt are skipped.
    """
    runner = CliRunner()
    
    with runner.isolated_filesystem() as tmp_dir:
        tmp_path = Path(tmp_dir)
        customers_dir = tmp_path / 'customers'
        customers_dir.mkdir()
        
        test_customer_dir = customers_dir / 'testcorp'
        test_customer_dir.mkdir()
        
        # Setup customer config
        (test_customer_dir / 'customer.yaml').write_text("""name: "Test Corp"
slug: testcorp
drive_folder_id: "test123"
""" )
        
        # Setup mock emails (3 emails)
        emails_dir = test_customer_dir / 'emails'
        emails_dir.mkdir()
        mock_emails = [
            {"id": "email1", "subject": "Test 1", "from": "test@testcorp.com"},
            {"id": "email2", "subject": "Test 2", "from": "test@testcorp.com"},
            {"id": "email3", "subject": "Test 3", "from": "test@testcorp.com"},
        ]
        (emails_dir / 'emails.json').write_text(json.dumps(mock_emails))
        
        # Pre-populate emails_processed.txt with 2 emails
        (test_customer_dir / 'emails_processed.txt').write_text("email1\nemail2\n")
        
        # Setup mock tasks
        tasks_dir = test_customer_dir / 'tasks'
        tasks_dir.mkdir()
        (tasks_dir / 'tasks.json').write_text(json.dumps([]))
        
        # Setup config
        (customers_dir / 'config.yaml').write_text("""use_mock_gemini: true
use_mock_data: true
skip_task_writes: false
""")

        # Create prompt.tpl in the XDG config home (tmp_path is set as XDG_CONFIG_HOME)
        config_dir_for_prompt = tmp_path / 'agentic-consult'
        config_dir_for_prompt.mkdir(parents=True, exist_ok=True)
        (config_dir_for_prompt / 'prompt.tpl').write_text("""Customer: <CUSTOMER>
Emails: <EMAILS>
Tasks: <TASKS>
""")
        
        # Setup mock Gemini response
        repo_root = Path(__file__).parent.parent.parent.parent
        mock_deltas = {
            "tasks": {"create": [], "update": []},
            "ignoring": [{"email_id": "email3", "disposition": "informational", "reason": "No action needed"}], "issues": {"update": []}
        }
        (repo_root / 'mock-deltas.json').write_text(json.dumps(mock_deltas))
        
        # Mock subprocess
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(mock_deltas), stderr='')
            
            env = {'CUSTOMERS_DIR': str(customers_dir)}
            
            result = runner.invoke(
                main,
                ['refresh', 'testcorp', '--no-dry-run', '--skip-fetch'],
                env=env
            )
            with open(emails_dir / 'emails.json', 'r') as f:
                filtered_emails = json.load(f)
            
            # Should only have email3 (the unprocessed one)
            assert len(filtered_emails) == 1
            assert filtered_emails[0]['id'] == 'email3'
            
            # Verify email3 was added to processed list
            processed = load_processed_emails(test_customer_dir)
            assert processed == {"email1", "email2", "email3"}


def test_local_emails_not_processed_are_processed():
    """
    Permutation 2: Local emails.json + not processed → Process
    Verify that emails in local emails.json that are NOT in emails_processed.txt are processed.
    """
    runner = CliRunner()
    
    with runner.isolated_filesystem() as tmp_dir:
        tmp_path = Path(tmp_dir)
        customers_dir = tmp_path / 'customers'
        customers_dir.mkdir()
        
        test_customer_dir = customers_dir / 'testcorp'
        test_customer_dir.mkdir()
        
        # Setup customer config
        (test_customer_dir / 'customer.yaml').write_text("""name: "Test Corp"
slug: testcorp
""" )
        
        # Setup mock emails (all unprocessed)
        emails_dir = test_customer_dir / 'emails'
        emails_dir.mkdir()
        mock_emails = [
            {"id": "email1", "subject": "Test 1", "from": "test@testcorp.com"},
            {"id": "email2", "subject": "Test 2", "from": "test@testcorp.com"},
        ]
        (emails_dir / 'emails.json').write_text(json.dumps(mock_emails))
        
        # No emails_processed.txt file (all emails are new)
        
        # Setup mock tasks
        # Setup config
        (customers_dir / 'config.yaml').write_text("""use_mock_gemini: true
use_mock_data: true
skip_task_writes: false
""")

        # Create prompt.tpl in the XDG config home (tmp_path is set as XDG_CONFIG_HOME)
        config_dir_for_prompt = tmp_path / 'agentic-consult'
        config_dir_for_prompt.mkdir(parents=True, exist_ok=True)
        (config_dir_for_prompt / 'prompt.tpl').write_text("""Customer: <CUSTOMER>
Emails: <EMAILS>
Tasks: <TASKS>
""")
        
        # Setup mock Gemini response
        repo_root = Path(__file__).parent.parent.parent.parent
        mock_deltas = {
            "tasks": {"create": [], "update": []},
            "ignoring": [{"email_id": "email1", "disposition": "informational", "reason": "No action needed"}, {"email_id": "email2", "disposition": "informational", "reason": "No action needed"}], "issues": {"update": []}
        }
        (repo_root / 'mock-deltas.json').write_text(json.dumps(mock_deltas))
        
        # Mock subprocess
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(mock_deltas), stderr='')
            
            env = {'CUSTOMERS_DIR': str(customers_dir)}
            
            result = runner.invoke(
                main,
                ['refresh', 'testcorp', '--no-dry-run'],
                env=env
            )
            assert result.exit_code == 0
            
            # Verify both emails were processed
            processed = load_processed_emails(test_customer_dir)
            assert processed == {"email1", "email2"}


def test_gmail_fetch_already_processed_are_skipped():
    """
    Permutation 3: Gmail query + already processed → Skip
    Verify that emails fetched from Gmail that are already in emails_processed.txt are skipped.
    """
    runner = CliRunner()
    
    with runner.isolated_filesystem() as tmp_dir:
        tmp_path = Path(tmp_dir)
        customers_dir = tmp_path / 'customers'
        customers_dir.mkdir()
        
        test_customer_dir = customers_dir / 'testcorp'
        test_customer_dir.mkdir()
        
        # Setup customer config
        (test_customer_dir / 'customer.yaml').write_text("""name: "Test Corp"
slug: testcorp
keywords: ["testcorp"]
""" )
        
        # Setup mock-emails.json (simulates Gmail fetch)
        mock_emails = [
            {"id": "email1", "subject": "Test 1", "from": "test@testcorp.com"},
            {"id": "email2", "subject": "Test 2", "from": "test@testcorp.com"},
            {"id": "email3", "subject": "Test 3", "from": "test@testcorp.com"},
        ]
        (test_customer_dir / 'mock-emails.json').write_text(json.dumps(mock_emails))
        
        # Pre-populate emails_processed.txt with 2 emails
        (test_customer_dir / 'emails_processed.txt').write_text("email1\nemail2\n")
        
        # Setup mock-server-tasks.json
        (test_customer_dir / 'mock-server-tasks.json').write_text(json.dumps([]))
        
        # Setup config (use_mock_data will use mock-emails.json)
        (customers_dir / 'config.yaml').write_text("""use_mock_gemini: true
use_mock_data: true
skip_task_writes: false
""")

        # Create prompt.tpl in the XDG config home (tmp_path is set as XDG_CONFIG_HOME)
        config_dir_for_prompt = tmp_path / 'agentic-consult'
        config_dir_for_prompt.mkdir(parents=True, exist_ok=True)
        (config_dir_for_prompt / 'prompt.tpl').write_text("""Customer: <CUSTOMER>
Emails: <EMAILS>
Tasks: <TASKS>
""")
        
        # Setup mock Gemini response
        repo_root = Path(__file__).parent.parent.parent.parent
        mock_deltas = {
            "tasks": {"create": [], "update": []},
            "ignoring": [{"email_id": "email3", "disposition": "informational", "reason": "No action needed"}], "issues": {"update": []}
        }
        (repo_root / 'mock-deltas.json').write_text(json.dumps(mock_deltas))
        
        # Mock subprocess
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(mock_deltas), stderr='')
            
            env = {'CUSTOMERS_DIR': str(customers_dir)}
            
            result = runner.invoke(
                main,
                ['refresh', 'testcorp', '--no-dry-run'],
                env=env
            )
            assert result.exit_code == 0
            
            # Verify only email3 was processed
            emails_dir = test_customer_dir / 'emails'
            with open(emails_dir / 'emails.json', 'r') as f:
                cached_emails = json.load(f)
            
            # Should only have email3 after filtering
            assert len(cached_emails) == 1
            assert cached_emails[0]['id'] == 'email3'
            
            # Verify email3 was added to processed list
            processed = load_processed_emails(test_customer_dir)
            assert processed == {"email1", "email2", "email3"}


def test_gmail_fetch_not_processed_are_processed():
    """
    Permutation 4: Gmail query + not processed → Process
    Verify that emails fetched from Gmail that are NOT in emails_processed.txt are processed.
    """
    runner = CliRunner()
    
    with runner.isolated_filesystem() as tmp_dir:
        tmp_path = Path(tmp_dir)
        customers_dir = tmp_path / 'customers'
        customers_dir.mkdir()
        
        test_customer_dir = customers_dir / 'testcorp'
        test_customer_dir.mkdir()
        
        # Setup customer config
        (test_customer_dir / 'customer.yaml').write_text("""name: "Test Corp"
slug: testcorp
keywords: ["testcorp"]
""" )
        
        # Setup mock-emails.json (simulates Gmail fetch with new emails)
        mock_emails = [
            {"id": "email1", "subject": "Test 1", "from": "test@testcorp.com"},
            {"id": "email2", "subject": "Test 2", "from": "test@testcorp.com"},
        ]
        (test_customer_dir / 'mock-emails.json').write_text(json.dumps(mock_emails))
        
        # No emails_processed.txt (all emails are new)
        
        # Setup mock-server-tasks.json
        (test_customer_dir / 'mock-server-tasks.json').write_text(json.dumps([]))
        
        # Setup config
        (customers_dir / 'config.yaml').write_text("""use_mock_gemini: true
use_mock_data: true
skip_task_writes: false
""")

        # Create prompt.tpl in the XDG config home (tmp_path is set as XDG_CONFIG_HOME)
        config_dir_for_prompt = tmp_path / 'agentic-consult'
        config_dir_for_prompt.mkdir(parents=True, exist_ok=True)
        (config_dir_for_prompt / 'prompt.tpl').write_text("""Customer: <CUSTOMER>
Emails: <EMAILS>
Tasks: <TASKS>
""")
        
        # Setup mock Gemini response
        repo_root = Path(__file__).parent.parent.parent.parent
        mock_deltas = {
            "tasks": {"create": [], "update": []},
            "ignoring": [{"email_id": "email1", "disposition": "informational", "reason": "No action needed"}, {"email_id": "email2", "disposition": "informational", "reason": "No action needed"}], "issues": {"update": []}
        }
        (repo_root / 'mock-deltas.json').write_text(json.dumps(mock_deltas))
        
        # Mock subprocess
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(mock_deltas), stderr='')
            
            env = {'CUSTOMERS_DIR': str(customers_dir)}
            
            # Run WITHOUT --skip-fetch to trigger "Gmail" fetch
            result = runner.invoke(
                main,
                ['refresh', 'testcorp', '--no-dry-run'],
                env=env
            )
            assert result.exit_code == 0
            
            # Verify both emails were processed
            processed = load_processed_emails(test_customer_dir)
            assert processed == {"email1", "email2"}
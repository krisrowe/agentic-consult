import tempfile
import json
import subprocess
from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner
from agentic_consult.cli.main import main
from agentic_consult.processing_state import load_processed_emails
from agentic_consult.gemini import GeminiAPIClient


def create_mock_subprocess_with_deltas(customer_dir, mock_deltas):
    """
    Creates a mock subprocess side_effect that writes deltas.json file.
    This is needed because mocked subprocess doesn't execute shell redirection.
    """
    def mock_subprocess_side_effect(*args, **kwargs):
        cmd = args[0] if args else kwargs.get('args', '')
        # Only write deltas.json when the Gemini command runs (has shell redirection)
        # Check for both 'deltas.json' and shell=True to avoid writing on other subprocess calls
        if isinstance(cmd, str) and 'deltas.json' in cmd and '>' in cmd:
            # Write the deltas file that would have been created by shell redirection
            deltas_path = customer_dir / 'deltas.json'
            deltas_path.write_text(json.dumps(mock_deltas))
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(mock_deltas), stderr='')
    return mock_subprocess_side_effect


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
        
        # Setup config with mock Gemini set to FALSE so it tries to use the API client (which we will mock)
        (customers_dir / 'config.yaml').write_text("""use_mock_gemini: false
use_mock_data: true
skip_task_writes: false
ticktick_project: Work
""")

        # Create prompt.tpl in the customers dir (global default)
        (customers_dir / 'prompt.tpl').write_text("""Customer: <CUSTOMER>
Emails: <EMAILS>
Tasks: <TASKS>
""")
        
        # Setup mock Gemini script response
        repo_root = Path(__file__).parent.parent.parent.parent
        mock_deltas = {
            "emails": [
                {
                    "id": "email1",
                    "deltas": [
                        {"type": "task_create", "title": "Task from email1", "priority": 1, "content": "Test"}
                    ]
                },
                {
                    "id": "email2",
                    "ignore": {"reason": "informational", "notes": "No action needed"}
                },
                {
                    "id": "email3",
                    "ignore": {"reason": "informational", "notes": "No action needed"}
                }
            ]
        }
        (repo_root / 'mock-deltas.json').write_text(json.dumps(mock_deltas))
        
        # Mock GeminiAPIClient and subprocess
        with patch('agentic_consult.cli.refresh.GeminiAPIClient') as MockClient, \
             patch('subprocess.run') as mock_run:
            
            # Setup Gemini mock
            mock_client_instance = MockClient.return_value
            mock_client_instance.generate_prompt_driven_json.return_value = mock_deltas
            
            # Setup TickTick subprocess mock
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            
            env = {'CUSTOMERS_DIR': str(customers_dir), 'XDG_CONFIG_HOME': str(tmp_path)}
            result = runner.invoke(
                main,
                ['refresh', 'testcorp', '--no-dry-run', '--skip-fetch'],
                env=env
            )
            
            # Verify command succeeded
            assert result.exit_code == 0, f"Command failed: {result.output}"
            
            # Verify Gemini was called
            assert mock_client_instance.generate_prompt_driven_json.called
            
            # Verify emails_processed.txt was created with acknowledged email IDs
            # email1 was acknowledged in tasks.create, email2 and email3 in ignoring
            processed_emails = load_processed_emails(test_customer_dir)
            assert processed_emails == {"email1", "email2", "email3"}, \
                f"Expected all 3 emails to be marked as processed (all acknowledged), got: {processed_emails}"


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
        (customers_dir / 'config.yaml').write_text("""use_mock_gemini: false
use_mock_data: true
skip_task_writes: false
""")

        # Create prompt.tpl in the customers dir (global default)
        (customers_dir / 'prompt.tpl').write_text("""Customer: <CUSTOMER>
Emails: <EMAILS>
Tasks: <TASKS>
""")
        
        # Setup mock Gemini response
        repo_root = Path(__file__).parent.parent.parent.parent
        mock_deltas = {
            "emails": [
                {
                    "id": "email1",
                    "ignore": {"reason": "informational", "notes": "No action needed"}
                },
                {
                    "id": "email2",
                    "ignore": {"reason": "informational", "notes": "No action needed"}
                }
            ]
        }
        (repo_root / 'mock-deltas.json').write_text(json.dumps(mock_deltas))
        
        # Mock GeminiAPIClient and subprocess
        with patch('agentic_consult.cli.refresh.GeminiAPIClient') as MockClient, \
             patch('subprocess.run') as mock_run:
            
            # Setup Gemini mock
            mock_client_instance = MockClient.return_value
            mock_client_instance.generate_prompt_driven_json.return_value = mock_deltas
            
            # Setup TickTick subprocess mock
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
            
            env = {'CUSTOMERS_DIR': str(customers_dir), 'XDG_CONFIG_HOME': str(tmp_path)}
            
            # First run - should process both emails
            result1 = runner.invoke(
                main,
                ['refresh', 'testcorp', '--no-dry-run', '--skip-fetch'],
                env=env
            )
            assert result1.exit_code == 0
            assert mock_client_instance.generate_prompt_driven_json.call_count == 1
            
            # Verify both emails were marked as processed (both in ignoring array)
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
            
            # Should succeed but skip all emails (so Gemini won't be called again)
            assert result2.exit_code == 0
            assert mock_client_instance.generate_prompt_driven_json.call_count == 1  # Still 1, no new call
            
            # Verify emails.json was NOT filtered (it should contain all emails)
            with open(emails_dir / 'emails.json', 'r') as f:
                all_emails = json.load(f)
            assert len(all_emails) == 2, "emails.json should still contain all emails"


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

        # Create prompt.tpl in the customers dir (global default)
        (customers_dir / 'prompt.tpl').write_text("""Customer: <CUSTOMER>
Emails: <EMAILS>
Tasks: <TASKS>
""")
        
        # Setup mock Gemini response
        repo_root = Path(__file__).parent.parent.parent.parent
        mock_deltas = {
            "emails": [
                {
                    "id": "email3",
                    "ignore": {"reason": "informational", "notes": "No action needed"}
                }
            ]
        }
        (repo_root / 'mock-deltas.json').write_text(json.dumps(mock_deltas))
        
        # Mock GeminiAPIClient and subprocess
        with patch('agentic_consult.cli.refresh.GeminiAPIClient') as MockClient, \
             patch('subprocess.run') as mock_run:
            
            # Setup Gemini mock
            mock_client_instance = MockClient.return_value
            mock_client_instance.generate_prompt_driven_json.return_value = mock_deltas
            
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
            
            env = {'CUSTOMERS_DIR': str(customers_dir), 'XDG_CONFIG_HOME': str(tmp_path)}
            
            result = runner.invoke(
                main,
                ['refresh', 'testcorp', '--no-dry-run', '--skip-fetch'],
                env=env
            )
            # Verify emails.json was NOT filtered
            with open(emails_dir / 'emails.json', 'r') as f:
                all_emails = json.load(f)
            assert len(all_emails) == 3
            
            # Verify email3 was added to processed list (acknowledged in ignoring array)
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
        
        # Setup config
        (customers_dir / 'config.yaml').write_text("""use_mock_gemini: true
use_mock_data: true
skip_task_writes: false
""")

        # Create prompt.tpl in the customers dir (global default)
        (customers_dir / 'prompt.tpl').write_text("""Customer: <CUSTOMER>
Emails: <EMAILS>
Tasks: <TASKS>
""")

        # Setup mock Gemini response
        repo_root = Path(__file__).parent.parent.parent.parent
        mock_deltas = {
            "emails": [
                {
                    "id": "email1",
                    "ignore": {"reason": "informational", "notes": "No action needed"}
                },
                {
                    "id": "email2",
                    "ignore": {"reason": "informational", "notes": "No action needed"}
                }
            ]
        }
        (repo_root / 'mock-deltas.json').write_text(json.dumps(mock_deltas))
        
        # Mock GeminiAPIClient and subprocess
        with patch('agentic_consult.cli.refresh.GeminiAPIClient') as MockClient, \
             patch('subprocess.run') as mock_run:
            
            # Setup Gemini mock
            mock_client_instance = MockClient.return_value
            mock_client_instance.generate_prompt_driven_json.return_value = mock_deltas
            
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
            
            env = {'CUSTOMERS_DIR': str(customers_dir), 'XDG_CONFIG_HOME': str(tmp_path)}
            
            result = runner.invoke(
                main,
                ['refresh', 'testcorp', '--no-dry-run'],
                env=env
            )
            assert result.exit_code == 0
            
            # Verify both emails were processed (both acknowledged in ignoring array)
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

        # Create prompt.tpl in the customers dir (global default)
        (customers_dir / 'prompt.tpl').write_text("""Customer: <CUSTOMER>
Emails: <EMAILS>
Tasks: <TASKS>
""")
        
        # Setup mock Gemini response
        repo_root = Path(__file__).parent.parent.parent.parent
        mock_deltas = {
            "emails": [
                {
                    "id": "email3",
                    "ignore": {"reason": "informational", "notes": "No action needed"}
                }
            ]
        }
        (repo_root / 'mock-deltas.json').write_text(json.dumps(mock_deltas))
        
        # Mock GeminiAPIClient and subprocess
        with patch('agentic_consult.cli.refresh.GeminiAPIClient') as MockClient, \
             patch('subprocess.run') as mock_run:
            
            # Setup Gemini mock
            mock_client_instance = MockClient.return_value
            mock_client_instance.generate_prompt_driven_json.return_value = mock_deltas
            
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
            
            env = {'CUSTOMERS_DIR': str(customers_dir), 'XDG_CONFIG_HOME': str(tmp_path)}
            
            result = runner.invoke(
                main,
                ['refresh', 'testcorp', '--no-dry-run'],
                env=env
            )
            assert result.exit_code == 0
            
            # Verify emails.json contains all emails (not filtered on disk)
            emails_dir = test_customer_dir / 'emails'
            with open(emails_dir / 'emails.json', 'r') as f:
                cached_emails = json.load(f)
            assert len(cached_emails) == 3
            
            # Verify email3 was added to processed list (acknowledged in ignoring)
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

        # Create prompt.tpl in the customers dir (global default)
        (customers_dir / 'prompt.tpl').write_text("""Customer: <CUSTOMER>
Emails: <EMAILS>
Tasks: <TASKS>
""")
        
        # Setup mock Gemini response
        repo_root = Path(__file__).parent.parent.parent.parent
        mock_deltas = {
            "emails": [
                {
                    "id": "email1",
                    "ignore": {"reason": "informational", "notes": "No action needed"}
                },
                {
                    "id": "email2",
                    "ignore": {"reason": "informational", "notes": "No action needed"}
                }
            ]
        }
        (repo_root / 'mock-deltas.json').write_text(json.dumps(mock_deltas))
        
        # Mock GeminiAPIClient and subprocess
        with patch('agentic_consult.cli.refresh.GeminiAPIClient') as MockClient, \
             patch('subprocess.run') as mock_run:
            
            # Setup Gemini mock
            mock_client_instance = MockClient.return_value
            mock_client_instance.generate_prompt_driven_json.return_value = mock_deltas
            
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
            
            env = {'CUSTOMERS_DIR': str(customers_dir), 'XDG_CONFIG_HOME': str(tmp_path)}
            
            # Run WITHOUT --skip-fetch to trigger "Gmail" fetch
            result = runner.invoke(
                main,
                ['refresh', 'testcorp', '--no-dry-run'],
                env=env
            )
            assert result.exit_code == 0
            
            # Verify both emails were processed (both acknowledged in ignoring array)
            processed = load_processed_emails(test_customer_dir)
            assert processed == {"email1", "email2"}
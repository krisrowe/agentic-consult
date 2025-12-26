import tempfile
import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from agentic_consult.cli.main import main
from agentic_consult.processing_state import load_processed_emails
from agentic_consult.gemini import GeminiAPIClient

def test_end_to_end_email_processing_tracking():
    """
    End-to-end test: Run refresh command with mock Gemini and verify emails_processed.txt is created.
    Uses mock Gemini, mock data, skip fetch.
    """
    runner = CliRunner()
    
    with runner.isolated_filesystem() as tmp_dir:
        tmp_path = Path(tmp_dir)
        customers_dir = tmp_path / 'customers'
        customers_dir.mkdir()
        
        test_customer_dir = customers_dir / 'testcorp'
        test_customer_dir.mkdir()
        
        # Setup customer config
        (test_customer_dir / 'customer.yaml').write_text("""name: \"Test Corp\"
slug: testcorp
drive_folder_id: \"test123\"
keywords: [\"testcorp\"]
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
        
        # Setup mock tasks (local only)
        tasks_dir = test_customer_dir / 'tasks'
        tasks_dir.mkdir()
        (tasks_dir / 'tasks.json').write_text(json.dumps([]))
        
        # Setup config: Disable sync_tasks to avoid network/provider calls
        (customers_dir / 'config.yaml').write_text("""use_mock_gemini: false
use_mock_data: true
skip_task_writes: false
sync_tasks: false
ticktick_project: Work
""")

        # Create prompt.tpl in the customers dir (global default)
        (customers_dir / 'prompt.tpl').write_text("""Customer: <CUSTOMER>
Emails: <EMAILS>
Tasks: <TASKS>
""")
        
        # Setup mock Gemini output
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
        
        # Mock GeminiAPIClient
        with patch('agentic_consult.cli.refresh.GeminiAPIClient') as MockClient:
            
            # Setup Gemini mock
            mock_client_instance = MockClient.return_value
            mock_client_instance.generate_prompt_driven_json.return_value = mock_deltas
            
            env = {'CUSTOMERS_DIR': str(customers_dir), 'XDG_CONFIG_HOME': str(tmp_path)}
            
            # Note: --skip-fetch avoids calling fetch_and_cache_emails (network)
            # sync_tasks: false avoids calling provider (network)
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
            processed_emails = load_processed_emails(test_customer_dir)
            assert processed_emails == {"email1", "email2", "email3"}, \
                f"Expected all 3 emails to be marked as processed, got: {processed_emails}"
            
            # Verify local task was created
            tasks_file = test_customer_dir / 'tasks' / 'tasks.json'
            assert tasks_file.exists()
            with open(tasks_file) as f:
                tasks = json.load(f)
            assert len(tasks) == 1
            assert tasks[0]['title'] == "Task from email1"
            assert tasks[0]['is_dirty'] is True


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
        
        (test_customer_dir / 'customer.yaml').write_text("""name: \"Test Corp\"
slug: testcorp
drive_folder_id: \"test123\"
""" )
        
        emails_dir = test_customer_dir / 'emails'
        emails_dir.mkdir()
        mock_emails = [
            {"id": "email1", "subject": "Test 1", "from": "test@testcorp.com"},
            {"id": "email2", "subject": "Test 2", "from": "test@testcorp.com"},
        ]
        (emails_dir / 'emails.json').write_text(json.dumps(mock_emails))
        
        tasks_dir = test_customer_dir / 'tasks'
        tasks_dir.mkdir()
        (tasks_dir / 'tasks.json').write_text(json.dumps([]))
        
        (customers_dir / 'config.yaml').write_text("""use_mock_gemini: false
use_mock_data: true
skip_task_writes: false
sync_tasks: false
""")

        (customers_dir / 'prompt.tpl').write_text("""Customer: <CUSTOMER>
Emails: <EMAILS>
Tasks: <TASKS>
""")
        
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
        
        with patch('agentic_consult.cli.refresh.GeminiAPIClient') as MockClient:
            mock_client_instance = MockClient.return_value
            mock_client_instance.generate_prompt_driven_json.return_value = mock_deltas
            
            env = {'CUSTOMERS_DIR': str(customers_dir), 'XDG_CONFIG_HOME': str(tmp_path)}
            
            # First run
            result1 = runner.invoke(
                main,
                ['refresh', 'testcorp', '--no-dry-run', '--skip-fetch'],
                env=env
            )
            assert result1.exit_code == 0
            assert mock_client_instance.generate_prompt_driven_json.call_count == 1
            
            processed = load_processed_emails(test_customer_dir)
            assert processed == {"email1", "email2"}
            
            # Second run
            (emails_dir / 'emails.json').write_text(json.dumps(mock_emails)) # Reset cache
            
            result2 = runner.invoke(
                main,
                ['refresh', 'testcorp', '--no-dry-run', '--skip-fetch'],
                env=env
            )
            
            assert result2.exit_code == 0
            # Gemini should NOT be called again because filtered emails list is empty
            assert mock_client_instance.generate_prompt_driven_json.call_count == 1


def test_local_emails_already_processed_are_skipped():
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        tmp_path = Path(tmp_dir)
        customers_dir = tmp_path / 'customers'
        customers_dir.mkdir()
        test_customer_dir = customers_dir / 'testcorp'
        test_customer_dir.mkdir()
        
        (test_customer_dir / 'customer.yaml').write_text("""name: \"Test Corp\"
slug: testcorp
drive_folder_id: \"test123\"
""" )
        
        emails_dir = test_customer_dir / 'emails'
        emails_dir.mkdir()
        mock_emails = [
            {"id": "email1", "subject": "Test 1", "from": "test@testcorp.com"},
            {"id": "email2", "subject": "Test 2", "from": "test@testcorp.com"},
            {"id": "email3", "subject": "Test 3", "from": "test@testcorp.com"},
        ]
        (emails_dir / 'emails.json').write_text(json.dumps(mock_emails))
        
        (test_customer_dir / 'emails_processed.txt').write_text("email1\nemail2\n")
        
        tasks_dir = test_customer_dir / 'tasks'
        tasks_dir.mkdir()
        (tasks_dir / 'tasks.json').write_text(json.dumps([]))
        
        (customers_dir / 'config.yaml').write_text("""use_mock_gemini: false
use_mock_data: true
skip_task_writes: false
sync_tasks: false
""")
        (customers_dir / 'prompt.tpl').write_text("Prompt")
        
        mock_deltas = {
            "emails": [
                {
                    "id": "email3",
                    "ignore": {"reason": "informational"}
                }
            ]
        }
        
        with patch('agentic_consult.cli.refresh.GeminiAPIClient') as MockClient:
            mock_client_instance = MockClient.return_value
            mock_client_instance.generate_prompt_driven_json.return_value = mock_deltas
            
            env = {'CUSTOMERS_DIR': str(customers_dir), 'XDG_CONFIG_HOME': str(tmp_path)}
            
            result = runner.invoke(
                main,
                ['refresh', 'testcorp', '--no-dry-run', '--skip-fetch'],
                env=env
            )
            processed = load_processed_emails(test_customer_dir)
            assert processed == {"email1", "email2", "email3"}


def test_local_emails_not_processed_are_processed():
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        tmp_path = Path(tmp_dir)
        customers_dir = tmp_path / 'customers'
        customers_dir.mkdir()
        test_customer_dir = customers_dir / 'testcorp'
        test_customer_dir.mkdir()
        
        (test_customer_dir / 'customer.yaml').write_text("""name: \"Test Corp\"
slug: testcorp
""" )
        
        emails_dir = test_customer_dir / 'emails'
        emails_dir.mkdir()
        mock_emails = [
            {"id": "email1", "subject": "Test 1"},
            {"id": "email2", "subject": "Test 2"},
        ]
        (emails_dir / 'emails.json').write_text(json.dumps(mock_emails))
        
        (customers_dir / 'config.yaml').write_text("""use_mock_gemini: false
use_mock_data: true
skip_task_writes: false
sync_tasks: false
""")
        (customers_dir / 'prompt.tpl').write_text("Prompt")

        mock_deltas = {
            "emails": [
                {"id": "email1", "ignore": {"reason": "informational"}},
                {"id": "email2", "ignore": {"reason": "informational"}}
            ]
        }
        
        # Corrected block with patch
        with patch('agentic_consult.cli.refresh.GeminiAPIClient') as MockClient, \
             patch('agentic_consult.cli.refresh.fetch_and_cache_emails') as mock_fetch:
            
            mock_client_instance = MockClient.return_value
            mock_client_instance.generate_prompt_driven_json.return_value = mock_deltas
            mock_fetch.return_value = (2, {'remote': 0, 'cache': 2})
            
            env = {'CUSTOMERS_DIR': str(customers_dir), 'XDG_CONFIG_HOME': str(tmp_path)}
            result = runner.invoke(main, ['refresh', 'testcorp', '--no-dry-run'], env=env)
            assert result.exit_code == 0
            
            processed = load_processed_emails(test_customer_dir)
            assert processed == {"email1", "email2"}


def test_gmail_fetch_already_processed_are_skipped():
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        tmp_path = Path(tmp_dir)
        customers_dir = tmp_path / 'customers'
        customers_dir.mkdir()
        test_customer_dir = customers_dir / 'testcorp'
        test_customer_dir.mkdir()
        
        (test_customer_dir / 'customer.yaml').write_text("""name: \"Test Corp\"
slug: testcorp
keywords: [\"testcorp\"]
""" )
        (test_customer_dir / 'emails_processed.txt').write_text("email1\nemail2\n")
        (test_customer_dir / 'tasks').mkdir()
        (test_customer_dir / 'tasks' / 'tasks.json').write_text("[]")
        
        (customers_dir / 'config.yaml').write_text("use_mock_gemini: false\nuse_mock_data: true\nsync_tasks: false\n")
        (customers_dir / 'prompt.tpl').write_text("Prompt")
        
        mock_deltas = {"emails": [{"id": "email3", "ignore": {"reason": "informational"}}]}
        
        # Write emails.json directly
        emails_dir = test_customer_dir / 'emails'
        emails_dir.mkdir()
        (emails_dir / 'emails.json').write_text(json.dumps([
            {"id": "email1"}, {"id": "email2"}, {"id": "email3"}
        ]))

        with patch('agentic_consult.cli.refresh.GeminiAPIClient') as MockClient, \
             patch('agentic_consult.cli.refresh.fetch_and_cache_emails') as mock_fetch:
            
            mock_client_instance = MockClient.return_value
            mock_client_instance.generate_prompt_driven_json.return_value = mock_deltas
            mock_fetch.return_value = (0, {})
            
            env = {'CUSTOMERS_DIR': str(customers_dir), 'XDG_CONFIG_HOME': str(tmp_path)}
            result = runner.invoke(main, ['refresh', 'testcorp', '--no-dry-run'], env=env)
            assert result.exit_code == 0
            
            processed = load_processed_emails(test_customer_dir)
            assert processed == {"email1", "email2", "email3"}


def test_gmail_fetch_not_processed_are_processed():
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        tmp_path = Path(tmp_dir)
        customers_dir = tmp_path / 'customers'
        customers_dir.mkdir()
        test_customer_dir = customers_dir / 'testcorp'
        test_customer_dir.mkdir()
        
        (test_customer_dir / 'customer.yaml').write_text("""name: \"Test Corp\"
slug: testcorp
keywords: [\"testcorp\"]
""" )
        (test_customer_dir / 'tasks').mkdir()
        (test_customer_dir / 'tasks' / 'tasks.json').write_text("[]")
        
        (customers_dir / 'config.yaml').write_text("use_mock_gemini: true\nuse_mock_data: true\nsync_tasks: false\n")
        (customers_dir / 'prompt.tpl').write_text("Prompt")
        
        # Write emails.json directly (simulating successful fetch)
        emails_dir = test_customer_dir / 'emails'
        emails_dir.mkdir()
        (emails_dir / 'emails.json').write_text(json.dumps([
            {"id": "email1"}, {"id": "email2"}
        ]))
        
        mock_deltas = {"emails": [{"id": "email1", "ignore": {}}, {"id": "email2", "ignore": {}}]}
        
        with patch('agentic_consult.cli.refresh.GeminiAPIClient') as MockClient, \
             patch('agentic_consult.cli.refresh.fetch_and_cache_emails') as mock_fetch:
            
            mock_client_instance = MockClient.return_value
            mock_client_instance.generate_prompt_driven_json.return_value = mock_deltas
            mock_fetch.return_value = (0, {})
            
            env = {'CUSTOMERS_DIR': str(customers_dir), 'XDG_CONFIG_HOME': str(tmp_path)}
            result = runner.invoke(main, ['refresh', 'testcorp', '--no-dry-run'], env=env)
            assert result.exit_code == 0
            
            processed = load_processed_emails(test_customer_dir)
            assert processed == {"email1", "email2"}

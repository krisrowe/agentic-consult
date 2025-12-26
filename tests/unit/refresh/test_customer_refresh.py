import os
import tempfile
from pathlib import Path
import subprocess
import json
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from agentic_consult.cli.main import main
from agentic_consult.refresh import build_prompt

def test_refresh_dry_run():
    """Test that refresh command works in dry-run mode with minimal setup."""
    runner = CliRunner()
    
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        
        customers_dir = tmp_path / 'customers' / 'fakecorp'
        customers_dir.mkdir(parents=True)
        
        (customers_dir / 'customer.yaml').write_text("""
name: "FakeCorp Test"
slug: fakecorp
drive_folder_id: 'REFRESH123'
keywords:
  - fakecorp
""")
        
        (customers_dir / 'emails').mkdir(parents=True)
        (customers_dir / 'emails' / 'emails.json').write_text(json.dumps([{"id": "msg1", "snippet": "Test email snippet"}]))

        prompt_tpl = tmp_path / 'prompt.tpl'
        prompt_tpl.write_text("""
Customer: <CUSTOMER>
Project: <PROJECT>
Today: <TODAY>
Issues Dir: <ISSUES_DIR>
""")
        
        env = os.environ.copy()
        env['CUSTOMERS_DIR'] = str(customers_dir.parent)
        env['XDG_CONFIG_HOME'] = str(tmp_path)
        
        (customers_dir.parent / 'agentic-consult').mkdir(parents=True, exist_ok=True)
        (customers_dir.parent / 'agentic-consult' / 'prompt.tpl').write_text(prompt_tpl.read_text())
        
        with patch('agentic_consult.cli.refresh.fetch_and_cache_emails') as mock_fetch_and_cache_emails, \
             patch('agentic_consult.cli.refresh.fetch_and_cache_tasks') as mock_fetch_and_cache_tasks, \
             patch('subprocess.run') as mock_subprocess_run:
            
            mock_fetch_and_cache_emails.return_value = (1, {'remote': 1, 'cache': 0})
            mock_fetch_and_cache_tasks.return_value = (1, {})

            def mock_run_side_effect(*args, **kwargs):
                cmd = args[0]
                cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
                if 'gwsa mail search' in cmd_str:
                    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=json.dumps([{"id": "msg1", "snippet": "Test email snippet"}]))
                elif 'gwsa mail read' in cmd_str:
                    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=json.dumps({"id": "msg1", "subject": "Test Email", "body": "Body 1"}))
                return subprocess.CompletedProcess(args=cmd, returncode=1, stderr="Unknown command")
            
            mock_subprocess_run.side_effect = mock_run_side_effect
            
            result = runner.invoke(main, ['refresh', 'fakecorp'], env=env)
            
            assert result.exit_code == 0, f"Command failed with: {result.output}"
            assert 'FakeCorp Test' in result.output
            assert 'DRY_RUN=1' in result.output
            assert 'Gemini API generation' in result.output

def test_refresh_build_prompt():
    """Test that build_prompt substitutes placeholders correctly."""
    template = """
Customer: <CUSTOMER>
Search: <CUSTOMER_SEARCH>
Today: <TODAY>
Project: <PROJECT>
Reminder: <REMINDER_MINUTES>
Issues: <ISSUES_DIR>
"""
    
    config = {
        'ticktick_project': 'TestProject',
        'reminder_minutes': 10
    }
    
    customer = {
        'name': 'Test Customer Inc',
        'slug': 'testcustomer'
    }
    
    with tempfile.TemporaryDirectory() as tmp:
        env = os.environ.copy()
        env['ISSUES_DIR'] = tmp
        
        result = build_prompt(template, config, customer)
        
        assert 'Customer: Test Customer Inc' in result
        assert 'Search: Test Customer Inc' in result
        assert 'Project: TestProject' in result
        assert 'Reminder: 10' in result
        assert '<CUSTOMER>' not in result
        assert '<TODAY>' not in result
        assert '<PROJECT>' not in result

def test_refresh_no_dry_run():
    """Test refresh in --no-dry-run mode with mocked subprocess (full execution path)."""
    runner = CliRunner()
    
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        
        customers_dir = tmp_path / 'customers' / 'fakecorp'
        customers_dir.mkdir(parents=True)
        
        (customers_dir / 'customer.yaml').write_text("""
name: "FakeCorp Test"
slug: fakecorp
drive_folder_id: 'REFRESH456'
keywords:
  - fakecorp
""")
        
        (customers_dir / 'emails').mkdir(parents=True)
        (customers_dir / 'emails' / 'emails.json').write_text(json.dumps([{"id": "msg1", "snippet": "Test email snippet"}]))

        prompt_tpl = tmp_path / 'prompt.tpl'
        prompt_tpl.write_text("""
Customer: <CUSTOMER>
Today: <TODAY>
Issues: <ISSUES_DIR>
""")
        
        config_dir = tmp_path / 'agentic-consult'
        config_dir.mkdir(parents=True)
        (config_dir / 'prompt.tpl').write_text(prompt_tpl.read_text())
        (config_dir / 'config.yaml').write_text("use_mock_gemini: true\nuse_mock_data: true\n")
        
        env = os.environ.copy()
        env['CUSTOMERS_DIR'] = str(customers_dir.parent)
        env['XDG_CONFIG_HOME'] = str(tmp_path)
        
        with patch('agentic_consult.cli.refresh.fetch_and_cache_emails') as mock_fetch_and_cache_emails, \
             patch('agentic_consult.cli.refresh.fetch_and_cache_tasks') as mock_fetch_and_cache_tasks, \
             patch('subprocess.run') as mock_subprocess_run:
            
            mock_fetch_and_cache_emails.return_value = (1, {'remote': 1, 'cache': 0})
            mock_fetch_and_cache_tasks.return_value = (1, {})
            
            def mock_run_side_effect(*args, **kwargs):
                return subprocess.CompletedProcess(args=[], returncode=0, stdout="")
            
            mock_subprocess_run.side_effect = mock_run_side_effect
            
            result = runner.invoke(main, ['refresh', 'fakecorp', '--no-dry-run'], env=env)
            
            assert result.exit_code == 0, f"Command failed with: {result.output}"
            assert 'Gemini output saved' in result.output or 'Mock Gemini output saved' in result.output
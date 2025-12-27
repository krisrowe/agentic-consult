import os
import tempfile
from pathlib import Path
import subprocess
import json
from unittest.mock import patch
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
        
        config_dir = tmp_path / 'agentic-consult'
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / 'prompt.tpl').write_text(prompt_tpl.read_text())
        
        # Ensure sync_tasks is false for unit tests to avoid network calls
        (config_dir / 'settings.json').write_text(json.dumps({"sync_tasks": False}))

        with patch('agentic_consult.cli.refresh.fetch_and_cache_emails') as mock_fetch_and_cache_emails:
            
            mock_fetch_and_cache_emails.return_value = (1, {'remote': 1, 'cache': 0})

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
    """Test refresh in --no-dry-run mode (local logic only)."""
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
        
        # sync_tasks: false ensures we don't call the provider (network)
        (config_dir / 'settings.json').write_text(json.dumps({
            "use_mock_gemini": True,
            "use_mock_data": True,
            "sync_tasks": False
        }))
        
        env = os.environ.copy()
        env['CUSTOMERS_DIR'] = str(customers_dir.parent)
        env['XDG_CONFIG_HOME'] = str(tmp_path)
        
        with patch('agentic_consult.cli.refresh.fetch_and_cache_emails') as mock_fetch_and_cache_emails:
            
            mock_fetch_and_cache_emails.return_value = (1, {'remote': 1, 'cache': 0})
            
            # Pre-check: No archived files yet
            archive_dir = customers_dir / 'deltas_archive'
            assert not archive_dir.exists() or len(list(archive_dir.glob("*.json"))) == 0

            result = runner.invoke(main, ['refresh', 'fakecorp', '--no-dry-run'], env=env)
            
            assert result.exit_code == 0, f"Command failed with: {result.output}"
            
            # Outcome Verification: Check that a delta file was archived (implies created, processed, and moved)
            archive_dir = customers_dir / 'deltas_archive'
            assert archive_dir.exists()
            archived_files = list(archive_dir.glob("done_deltas_*.json"))
            assert len(archived_files) == 1, "Expected one archived delta file"


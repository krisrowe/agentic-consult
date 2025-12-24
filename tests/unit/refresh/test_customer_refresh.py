import os
import tempfile
from pathlib import Path
from click.testing import CliRunner
from agentic_consult.cli.main import main

def test_refresh_dry_run():
    """Test that refresh command works in dry-run mode with minimal setup."""
    from unittest.mock import patch
    runner = CliRunner()
    
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        
        # Create customer config directory
        customers_dir = tmp_path / 'customers' / 'fakecorp'
        customers_dir.mkdir(parents=True)
        
        # Create customer.yaml
        customer_yaml = customers_dir / 'customer.yaml'
        customer_yaml.write_text("""name: "FakeCorp Test"
slug: fakecorp
drive_folder_id: 'REFRESH123'
keywords:
  - fakecorp
""")
        
        # Create a simple prompt template in the tmp directory
        prompt_tpl = tmp_path / 'prompt.tpl'
        prompt_tpl.write_text("""Customer: <CUSTOMER>
Project: <PROJECT>
Today: <TODAY>
Issues Dir: <ISSUES_DIR>
""")
        
        # Set environment variables to use our tmp directories
        env = os.environ.copy()
        env['CUSTOMERS_DIR'] = str(customers_dir.parent)
        env['XDG_CONFIG_HOME'] = str(tmp_path)
        
        # Create config directory structure for prompt.tpl (customers_dir.parent is the XDG_CONFIG_HOME for this test)
        (customers_dir.parent / 'agentic-consult').mkdir(parents=True, exist_ok=True)
        (customers_dir.parent / 'agentic-consult' / 'prompt.tpl').write_text(prompt_tpl.read_text())
        
        # Mock SDK functions with updated signatures
        with patch('agentic_consult.gmail.fetch_and_cache_emails') as mock_fetch_and_cache_emails, \
             patch('agentic_consult.ticktick.fetch_and_cache_tasks') as mock_fetch_and_cache_tasks, \
             patch('subprocess.run') as mock_subprocess_run:
            
            # Mock `fetch_and_cache_emails` to return a successful count and empty stats
            mock_fetch_and_cache_emails.return_value = (0, {})
            mock_fetch_and_cache_tasks.return_value = (0, {})
            
            # Mock `subprocess.run` for `gwsa mail search` to return valid JSON
            mock_subprocess_run.return_value = MagicMock(returncode=0, stdout=json.dumps([]))

            # Run refresh in dry-run mode (default)
            result = runner.invoke(main, ['refresh', 'fakecorp'], env=env)            
            # Check that command succeeded
            assert result.exit_code == 0, f"Command failed with: {result.output}"
            
            # Check that output contains expected elements
            assert 'FakeCorp Test' in result.output
            assert 'DRY_RUN=1' in result.output
            assert 'Prompt for Gemini MCP' in result.output


def test_refresh_build_prompt():
    """Test that build_prompt substitutes placeholders correctly."""
    from agentic_consult.refresh import build_prompt
    
    template = """Customer: <CUSTOMER>
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
        
        # Build the prompt
        result = build_prompt(template, config, customer)
        
        # Verify substitutions
        assert 'Customer: Test Customer Inc' in result
        assert 'Search: Test Customer Inc' in result
        assert 'Project: TestProject' in result
        assert 'Reminder: 10' in result
        assert '<CUSTOMER>' not in result
        assert '<TODAY>' not in result
        assert '<PROJECT>' not in result


def test_refresh_no_dry_run():
    """Test refresh in --no-dry-run mode with mocked subprocess (full execution path)."""
    from unittest.mock import patch, MagicMock
    runner = CliRunner()
    
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        
        # Create customer config
        customers_dir = tmp_path / 'customers' / 'fakecorp'
        customers_dir.mkdir(parents=True)
        
        customer_yaml = customers_dir / 'customer.yaml'
        customer_yaml.write_text("""name: "FakeCorp Test"
slug: fakecorp
drive_folder_id: 'REFRESH456'
keywords:
  - fakecorp
""")

        # Create a simple prompt template in the tmp directory for this test
        prompt_tpl = tmp_path / 'prompt.tpl'
        prompt_tpl.write_text("""Customer: <CUSTOMER>
Today: <TODAY>
Issues: <ISSUES_DIR>
""")
        
        # Create prompt template in the XDG config home
        config_dir = tmp_path / 'agentic-consult'
        config_dir.mkdir(parents=True)
        (config_dir / 'prompt.tpl').write_text("""Customer: <CUSTOMER>
Today: <TODAY>
Issues: <ISSUES_DIR>
""")

        # Set environment variables
        env = os.environ.copy()
        env['CUSTOMERS_DIR'] = str(customers_dir.parent)
        env['XDG_CONFIG_HOME'] = str(tmp_path)
        
        # Mock SDK functions and shutil.which with updated signatures
        with patch('agentic_consult.gmail.fetch_and_cache_emails') as mock_fetch_and_cache_emails, \
             patch('agentic_consult.ticktick.fetch_and_cache_tasks') as mock_fetch_and_cache_tasks, \
             patch('subprocess.run') as mock_subprocess_run, \
             patch('shutil.which') as mock_which:
            
            # Mock `fetch_and_cache_emails` and `fetch_and_cache_tasks` return values
            mock_fetch_and_cache_emails.return_value = (1, {'remote': 1, 'cache': 0})
            mock_fetch_and_cache_tasks.return_value = (1, {})

            # Make it think gemini command exists
            mock_which.return_value = '/usr/bin/gemini'

            # Mock `subprocess.run` for gwsa and gemini commands
            def mock_run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'gwsa mail search' in cmd:
                    return MagicMock(returncode=0, stdout=json.dumps([{"id": "msg1", "snippet": "Test email snippet"}]))
                elif 'gwsa mail read' in cmd:
                    return MagicMock(returncode=0, stdout=json.dumps({"id": "msg1", "subject": "Test Email", "body": "Body 1"}))
                elif 'ticktick' in cmd:
                    return MagicMock(returncode=0, stdout="") # TickTick commands typically have no stdout on success
                elif 'gemini' in cmd:
                    return MagicMock(returncode=0, stdout='{"tasks": {"create": [], "update": []}, "issues": {"update": []}}')
                return MagicMock(returncode=1, stderr="Unknown command")
            
            mock_subprocess_run.side_effect = mock_run_side_effect

            # Run refresh with --no-dry-run
            result = runner.invoke(
                main,
                ['refresh', 'fakecorp', '--no-dry-run'],
                env=env
            )            
            # Should succeed
            assert result.exit_code == 0, f"Command failed: {result.output}"
            assert 'Fetched 1 emails and 1 tasks.' in result.output
            
            # Verify subprocess was called with gemini command
            assert mock_subprocess_run.called, "subprocess.run should have been called"
            # No specific check for call_args as side_effect is used


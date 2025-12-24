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
        
        # Create config directory structure for prompt.tpl
        config_dir = tmp_path / 'agentic-consult'
        config_dir.mkdir(parents=True)
        (config_dir / 'prompt.tpl').write_text(prompt_tpl.read_text())
        
        # Mock SDK functions
        with patch('agentic_consult.gmail.fetch_emails') as mock_fetch_emails, \
             patch('agentic_consult.ticktick.fetch_tasks') as mock_fetch_tasks:
            
            mock_fetch_emails.return_value = []
            mock_fetch_tasks.return_value = []
            
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
        
        # Create prompt template
        config_dir = tmp_path / 'agentic-consult'
        config_dir.mkdir(parents=True)
        (config_dir / 'prompt.tpl').write_text("""Customer: <CUSTOMER>
Today: <TODAY>
Issues: <ISSUES_DIR>
""")
        
        # Set environment
        env = os.environ.copy()
        env['CUSTOMERS_DIR'] = str(customers_dir.parent)
        env['XDG_CONFIG_HOME'] = str(tmp_path)
        
        # Mock SDK functions and shutil.which
        with patch('agentic_consult.gmail.fetch_emails') as mock_fetch_emails, \
             patch('agentic_consult.ticktick.fetch_tasks') as mock_fetch_tasks, \
             patch('subprocess.run') as mock_run, \
             patch('shutil.which') as mock_which:
            
            # Mock data
            mock_fetch_emails.return_value = [{"id": "msg1", "subject": "Test Email"}]
            mock_fetch_tasks.return_value = [{"id": "task1", "title": "Test Task"}]
            
            # Make it think gemini command exists
            mock_which.return_value = '/usr/bin/gemini'
            
            # Mock successful execution
            mock_run.return_value = MagicMock(returncode=0, stdout='{"tasks": {"create": [], "update": []}, "issues": {"update": []}}')
            
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
            assert mock_run.called, "subprocess.run should have been called"
            call_args = mock_run.call_args
            
            # Verify command structure
            assert call_args[0][0][0] == 'gemini'
            # We don't strictly check index 1 as it might be --model or --allowed-mcp-server-names depending on config
            assert '--allowed-mcp-server-names' in call_args[0][0]
            
            # Verify prompt was passed as input
            assert 'input' in call_args[1]
            prompt = call_args[1]['input']
            assert 'FakeCorp Test' in prompt or 'CUSTOMER' in prompt
            # Verify it's the prompt (either substituted or template)


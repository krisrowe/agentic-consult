import os
import shutil
import pytest
import tempfile
import json
from pathlib import Path
from click.testing import CliRunner
from agentic_consult.backup.orchestrator import BackupOrchestrator
from agentic_consult.backup.exceptions import (
    BackupConfigurationError,
    FolderAccessError
)
from agentic_consult.config import save_main_config
from agentic_consult.cli.backup import run as run_command

@pytest.fixture
def temp_dirs(monkeypatch):
    """
    Sets up temporary directories for backups and configuration.
    Sets environment variables to redirect the application to these dirs.
    """
    # 1. Backup storage
    backup_dir = tempfile.mkdtemp(prefix="consult_test_run_backups_")
    monkeypatch.setenv("LOCAL_BACKUPS_FOLDER", backup_dir)

    # 2. Config storage
    config_dir = tempfile.mkdtemp(prefix="consult_test_run_config_")
    monkeypatch.setenv("CONSULT_CONFIG_DIR", config_dir)
    
    # Ensure no interfering env var for ID override
    monkeypatch.delenv("BACKUPS_GOOGLE_DRIVE_FOLDER_ID", raising=False)

    yield backup_dir, config_dir

    # Cleanup
    if os.path.exists(backup_dir):
        shutil.rmtree(backup_dir)
    if os.path.exists(config_dir):
        shutil.rmtree(config_dir)

def test_backup_run_with_no_folder_id_error(temp_dirs):
    """
    Verify that the orchestrator raises BackupConfigurationError if no folder ID is configured.
    We rely on the empty clean config directory.
    """
    orchestrator = BackupOrchestrator()
    with pytest.raises(BackupConfigurationError):
        orchestrator.run_backups()

def test_backup_run_with_inaccessible_folder_id_error(temp_dirs):
    """
    Verify that the orchestrator raises FolderAccessError if the configured ID is invalid.
    We save a bad ID to the config file.
    """
    backup_dir, config_dir = temp_dirs
    non_existent_id = os.path.join(backup_dir, "non_existent_folder")
    
    # Save bad config
    save_main_config({'backups': {'google_drive_folder_id': non_existent_id}})
    
    orchestrator = BackupOrchestrator()
    with pytest.raises(FolderAccessError) as excinfo:
        orchestrator.run_backups()
    assert "not accessible" in str(excinfo.value)

def test_backup_result_summary_valid_json(temp_dirs):
    """
    Verify that --format json outputs valid JSON to stdout and logs details to stderr.
    """
    backup_dir, config_dir = temp_dirs
    
    # Setup valid config
    valid_id = os.path.join(backup_dir, "backups")
    os.makedirs(valid_id)
    save_main_config({'backups': {'google_drive_folder_id': valid_id}})
    
    # Create fake home/.gemini for the Gemini provider to find something
    gemini_home = os.path.join(os.path.expanduser("~"), ".gemini")
    os.makedirs(gemini_home, exist_ok=True)
    with open(os.path.join(gemini_home, "settings.json"), 'w') as f:
        f.write("{}")

    runner = CliRunner()
    # Run with --format json. We skip dirty to avoid failures if local ws is dirty in test env.
    # Note: local_repos provider scans ~/ws. In test env this might be anything.
    # We rely on the fact it won't crash.
    result = runner.invoke(run_command, ['--format', 'json', '--non-interactive', '--skip-dirty'])
    
    assert result.exit_code == 0
    
    # 1. Verify JSON output in stdout
    try:
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) >= 2 # Gemini + LocalRepo providers
        assert data[0]['provider_name'] == "Gemini Configuration"
    except json.JSONDecodeError:
        pytest.fail(f"Stdout is not valid JSON: {result.stdout}")

    # 2. Verify logs in stderr
    # CliRunner captures stderr separately? Yes, typically.
    # However, click.echo(err=True) goes to stderr.
    # result.stderr might be empty if everything went to stdout via print?
    # Wait, I changed print(..., file=sys.stderr).
    # Click runner captures sys.stderr too.
    
    # Check for specific stderr strings
    assert "Starting backup process..." in result.stderr
    assert "--- Running Provider:" in result.stderr

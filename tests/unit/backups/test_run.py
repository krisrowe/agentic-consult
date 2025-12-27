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
    
    # 3. Mock Home
    mock_home_dir = tempfile.mkdtemp(prefix="consult_test_home_")
    monkeypatch.setenv("BACKUPS_HOME_LOCAL_PATH", mock_home_dir)
    
    # Ensure no interfering env var for ID override
    monkeypatch.delenv("BACKUPS_GOOGLE_DRIVE_FOLDER_ID", raising=False)

    yield backup_dir, config_dir, mock_home_dir

    # Cleanup
    if os.path.exists(backup_dir):
        shutil.rmtree(backup_dir)
    if os.path.exists(config_dir):
        shutil.rmtree(config_dir)
    if os.path.exists(mock_home_dir):
        shutil.rmtree(mock_home_dir)


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
    backup_dir, config_dir, _ = temp_dirs
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
    backup_dir, config_dir, mock_home_dir = temp_dirs
    
    # Setup valid config
    valid_id = os.path.join(backup_dir, "backups")
    os.makedirs(valid_id)
    save_main_config({'backups': {'google_drive_folder_id': valid_id,
                                'user_home': {'paths': [
                                    ".gemini/settings.json",
                                    ".gemini/GEMINI.md",
                                    ".config/agentic-consult/settings.json"
                                ]}}})
    
    # Create fake home/.gemini for the Gemini provider to find something
    gemini_home = os.path.join(mock_home_dir, ".gemini")
    os.makedirs(gemini_home, exist_ok=True)
    with open(os.path.join(gemini_home, "settings.json"), 'w') as f: f.write("{}")
    with open(os.path.join(gemini_home, "GEMINI.md"), 'w') as f: f.write("test")
    runner = CliRunner()
    result = runner.invoke(run_command, ['--format', 'json', '--non-interactive', '--skip-dirty'])
    
    assert result.exit_code == 0
    
    # 1. Verify JSON output in stdout
    try:
        data = json.loads(result.stdout)
        assert isinstance(data, dict)
        assert "Home" in data # Check for one of the provider types
    except json.JSONDecodeError:
        pytest.fail(f"Stdout is not valid JSON: {result.stdout}")

    # 2. Verify logs in stderr
    assert "Starting backup process..." in result.stderr
    assert "--- Running Provider:" in result.stderr
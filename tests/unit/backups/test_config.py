import os
import shutil
import pytest
import tempfile
import json
from pathlib import Path
from agentic_consult.backup.config_manager import BackupConfigManager
from agentic_consult.config import load_main_config
from agentic_consult.backup.exceptions import (
    FolderAccessError,
    FolderExistsError,
    FolderNotFoundError,
    InvalidFolderNameError
)

@pytest.fixture
def temp_dirs(monkeypatch):
    """
    Sets up temporary directories for backups and configuration.
    Sets environment variables to redirect the application to these dirs.
    """
    # 1. Backup storage
    backup_dir = tempfile.mkdtemp(prefix="consult_test_backups_")
    monkeypatch.setenv("LOCAL_BACKUPS_FOLDER", backup_dir)

    # 2. Config storage
    config_dir = tempfile.mkdtemp(prefix="consult_test_config_")
    monkeypatch.setenv("CONSULT_CONFIG_DIR", config_dir)

    yield backup_dir, config_dir

    # Cleanup
    if os.path.exists(backup_dir):
        shutil.rmtree(backup_dir)
    if os.path.exists(config_dir):
        shutil.rmtree(config_dir)

def test_backup_config_create_folder_success(temp_dirs):
    """Verify that a new backup folder can be created successfully and config is updated."""
    backup_dir, config_dir = temp_dirs
    manager = BackupConfigManager()
    folder_name = "NewBackupFolder"
    
    assert not os.path.exists(os.path.join(backup_dir, folder_name))
    
    final_id = manager.configure_drive_folder(folder_name=folder_name, folder_id=None, create=True)
    
    # Verify folder was created
    expected_path = os.path.join(backup_dir, folder_name)
    assert os.path.exists(expected_path)
    assert final_id == expected_path

    # Verify config was updated
    config = load_main_config()
    assert config.get('backups_google_drive_folder_id') == final_id

def test_backup_config_create_folder_exists_error(temp_dirs):
    """Ensure an error is raised if --create is used but the folder already exists."""
    backup_dir, _ = temp_dirs
    manager = BackupConfigManager()
    folder_name = "ExistingFolder"
    os.makedirs(os.path.join(backup_dir, folder_name))
    
    with pytest.raises(FolderExistsError):
        manager.configure_drive_folder(folder_name=folder_name, folder_id=None, create=True)

def test_backup_config_folder_not_found_error(temp_dirs):
     """Ensure an error is raised if a folder name is given without --create and it doesn't exist."""
     manager = BackupConfigManager()
     folder_name = "MissingFolder"
     
     with pytest.raises(FolderNotFoundError):
         manager.configure_drive_folder(folder_name=folder_name, folder_id=None, create=False)

def test_backup_config_with_inaccessible_folder_id_error(temp_dirs):
    """Ensure an error is raised when a non-existent folder ID is provided."""
    manager = BackupConfigManager()
    bad_id = "/path/to/an/unlikely/place/to/exist"
    
    with pytest.raises(FolderAccessError):
        manager.configure_drive_folder(folder_name=None, folder_id=bad_id, create=False)

def test_backup_config_folder_name_missing_error(temp_dirs):
    """Ensure an error is raised if neither folder_name nor folder_id is provided."""
    manager = BackupConfigManager()
    with pytest.raises(ValueError, match="must specify either folder_name or folder_id"):
        manager.configure_drive_folder(folder_name=None, folder_id=None, create=False)

def test_backup_config_invalid_folder_name_error(temp_dirs):
    """Ensure folder names with path separators are rejected."""
    manager = BackupConfigManager()
    with pytest.raises(InvalidFolderNameError):
        manager.configure_drive_folder(folder_name="Invalid/Name", folder_id=None, create=True)
"""
Factory for BackupsFolderProvider.

Philosophy:
We support a 'LocalBackupsFolderProvider' to enable end-to-end testing without
network I/O, mocking frameworks, or over-mocking. This allows tests to verify
the entire logic flow using a real (but local) file system backend.

If the environment variable 'LOCAL_BACKUPS_FOLDER' is set, this factory returns
a LocalBackupsFolderProvider rooted at that path. Otherwise, it returns the
default GoogleDriveBackupsFolderProvider.
"""
import os
from agentic_consult.backup.folder_providers.base import BackupsFolderProvider
from agentic_consult.backup.folder_providers.drive import GoogleDriveBackupsFolderProvider
from agentic_consult.backup.folder_providers.local import LocalBackupsFolderProvider

def get_folder_provider() -> BackupsFolderProvider:
    """
    Returns the appropriate folder provider based on environment configuration.
    """
    local_root = os.environ.get("LOCAL_BACKUPS_FOLDER")
    if local_root:
        return LocalBackupsFolderProvider(root_path=local_root)
    return GoogleDriveBackupsFolderProvider()

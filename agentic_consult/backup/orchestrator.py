import click
import sys
from typing import List, Dict, Any
from agentic_consult.config import load_main_config, get_backups_google_drive_folder_id
from agentic_consult.backup.folder_providers.factory import get_folder_provider
from agentic_consult.backup.providers.base import BackupProvider
from agentic_consult.backup.providers.user_home import UserHomeBackup
from agentic_consult.backup.providers.local_repos import LocalRepoBackup
from agentic_consult.backup.providers.remote_repos import RemoteRepoBackup
from agentic_consult.backup.exceptions import BackupConfigurationError, FolderAccessError
from agentic_consult.backup.results import ProviderResult

class BackupOrchestrator:
    """
    Orchestrates the execution of all backup providers.
    """
    def __init__(self):
        self.provider = get_folder_provider()
        self.providers: List[BackupProvider] = [
            UserHomeBackup(),
            LocalRepoBackup(),
            RemoteRepoBackup()
        ]

    def run_backups(self, force: bool = False, skip_dirty: bool = False, interactive: bool = True, dry_run: bool = False) -> List[ProviderResult]:
        """
        Runs all configured backup providers and returns their results.
        """
        folder_id = get_backups_google_drive_folder_id()
        if not folder_id:
            raise BackupConfigurationError("Backup folder not configured. Run 'consult backup config' first.")

        # Validate access before starting
        if not self.provider.find_file_by_id(folder_id):
             raise FolderAccessError(f"Configured backup folder ID '{folder_id}' is not accessible.")

        config_data = load_main_config()
        options = {
            'force': force,
            'skip_dirty': skip_dirty,
            'interactive': interactive,
            'dry_run': dry_run
        }

        print("Starting backup process...", file=sys.stderr)
        results = []
        
        for provider in self.providers:
            print(f"\n--- Running Provider: {provider.name} ---", file=sys.stderr)
            result = provider.run(config_data, options)
            results.append(result)
            
            # Print status line to stderr for immediate feedback
            status_color = "green" if result.status == "success" else "yellow" if result.status == "skipped" else "red"
            click.secho(f"Status: {result.status.upper()}", fg=status_color, err=True)
            click.echo(f"Message: {result.message}", err=True)
            
        print("\nBackup process completed.", file=sys.stderr)
        return results
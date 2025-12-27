import os
import sys
from typing import Dict, Any, List
from agentic_consult.backup.providers.base import BackupProvider
from agentic_consult.backup.folder_providers.factory import get_folder_provider
from agentic_consult.config import get_backups_google_drive_folder_id
from agentic_consult.backup.results import ProviderResult, BackupItemResult, BackupStatus

class GeminiConfigBackup(BackupProvider):
    @property
    def name(self) -> str:
        return "Gemini Configuration"

    def run(self, config: Dict[str, Any], options: Dict[str, Any]) -> ProviderResult:
        folder_provider = get_folder_provider()
        home_dir = os.path.expanduser("~")
        gemini_dir = os.path.join(home_dir, ".gemini")
        
        items = []
        target_folder_id = get_backups_google_drive_folder_id()
        if not target_folder_id:
             return ProviderResult(self.name, "failure", "Backup folder not configured.", [])
        
        try:
            provider_folder_id = folder_provider.ensure_folder_path(["home", ".gemini"], root_id=target_folder_id)
            
            files_to_backup = ["settings.json", "GEMINI.md"]
            success_count = 0
            
            for filename in files_to_backup:
                local_path = os.path.join(gemini_dir, filename)
                if os.path.exists(local_path):
                    try:
                        folder_provider.sync_file(local_path, provider_folder_id)
                        items.append(BackupItemResult(filename, BackupStatus.SUCCESS, "Synced"))
                        success_count += 1
                    except Exception as e:
                        print(f"Error backing up {filename}: {e}", file=sys.stderr)
                        items.append(BackupItemResult(filename, BackupStatus.FAILED, str(e)))
                else:
                    print(f"Skipping {filename}: not found at {local_path}", file=sys.stderr)
                    items.append(BackupItemResult(filename, BackupStatus.SKIPPED, "File not found locally"))
            
            return ProviderResult(
                self.name, 
                "success", 
                f"Backed up {success_count} files", 
                items
            )
        except Exception as e:
            return ProviderResult(self.name, "failure", str(e), items)

import os
import sys
from pathlib import Path
from typing import Dict, Any, List
from agentic_consult.backup.providers.base import BackupProvider
from agentic_consult.backup.folder_providers.factory import get_folder_provider
from agentic_consult.config import get_backups_google_drive_folder_id, get_consult_config_dir
from agentic_consult.backup.results import ProviderResult, BackupItemResult, BackupStatus

class UserHomeBackup(BackupProvider):
    @property
    def name(self) -> str:
        return "User Home Configuration"

    def run(self, config: Dict[str, Any], options: Dict[str, Any]) -> ProviderResult:
        user_files_root_dir = os.environ.get("BACKUPS_HOME_LOCAL_PATH") or os.path.expanduser("~")
        
        user_home_config = config.get('backups', {}).get('user_home', {})
        enabled = user_home_config.get('enabled', True)
        
        if not enabled:
            return ProviderResult(self.name, "skipped", "Provider disabled in configuration", [])

        paths = user_home_config.get('paths', [])
        if not paths:
             return ProviderResult(self.name, "failure", "No paths configured.", [])

        folder_provider = get_folder_provider()
        items = []
        target_folder_id = get_backups_google_drive_folder_id()
        if not target_folder_id:
             return ProviderResult(self.name, "failure", "Backup folder not configured.", [])
        
        try:
            provider_root_id = folder_provider.ensure_folder_path(["home"], root_id=target_folder_id)
            success_count = 0
            
            for rel_path in paths:
                local_path: Path
                
                if rel_path == ".config/agentic-consult/settings.json":
                    local_path = get_consult_config_dir() / "settings.json"
                else:
                    local_path = Path(user_files_root_dir) / rel_path
                
                if not os.path.exists(local_path):
                    items.append(BackupItemResult(rel_path, BackupStatus.NOT_FOUND, "File not found locally", type="Home"))
                    continue

                try:
                    drive_parent_parts = [p for p in Path(rel_path).parts if p != '.'][:-1]
                    file_name_for_drive = Path(rel_path).name
                    
                    current_drive_parent_id = provider_root_id
                    if drive_parent_parts:
                        current_drive_parent_id = folder_provider.ensure_folder_path(drive_parent_parts, root_id=provider_root_id)
                    
                    folder_provider.sync_file(local_path, current_drive_parent_id, name=file_name_for_drive)
                    items.append(BackupItemResult(rel_path, BackupStatus.SUCCESS, "Synced", type="Home"))
                    success_count += 1
                    
                except Exception as e:
                    items.append(BackupItemResult(rel_path, BackupStatus.FAILED, str(e), type="Home"))
            
            return ProviderResult(self.name, "success", f"Backed up {success_count} files", items)
        except Exception as e:
            return ProviderResult(self.name, "failure", str(e), items)
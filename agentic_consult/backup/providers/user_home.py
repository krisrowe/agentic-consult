import os
import sys
import hashlib
from pathlib import Path
from typing import Dict, Any, List
from agentic_consult.backup.providers.base import BackupProvider
from agentic_consult.backup.folder_providers.factory import get_folder_provider
from agentic_consult.config import get_backups_google_drive_folder_id, get_consult_config_dir, get_settings_dir
from agentic_consult.backup.results import ProviderResult, BackupItemResult, BackupStatus

def get_local_md5(file_path):
    """Calculates the MD5 hash of a local file."""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

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
                # Dynamic Variable Substitution
                resolved_path_str = rel_path
                if "$TOOL_SETTINGS_DIR" in resolved_path_str:
                    resolved_path_str = resolved_path_str.replace("$TOOL_SETTINGS_DIR", str(get_settings_dir()))
                
                # Resolve to Absolute Local Path
                if os.path.isabs(resolved_path_str):
                    local_path = Path(resolved_path_str)
                else:
                    local_path = Path(user_files_root_dir) / resolved_path_str
                
                if not os.path.exists(local_path):
                    items.append(BackupItemResult(rel_path, BackupStatus.NOT_FOUND, "File/Folder not found locally", type="Home"))
                    continue

                # Determine Drive Structure relative to Home
                # Try to make local_path relative to user_files_root_dir
                try:
                    # If it's relative to home, preserve that structure
                    relative_path_for_drive = local_path.relative_to(user_files_root_dir)
                except ValueError:
                    # Fallback for paths outside of home (e.g. /etc/ or env var overrides)
                    # Use the basename at the root of the backup folder to avoid messy absolute trees
                    # e.g. /tmp/config/settings.json -> settings.json (in root) or config/settings.json
                    # Let's try to preserve at least the parent folder name if it's a file
                    if os.path.isfile(local_path):
                         # settings.json -> settings.json
                         relative_path_for_drive = Path(local_path.name)
                    else:
                         # directory -> directory_name
                         relative_path_for_drive = Path(local_path.name)

                # Recursive Directory Support
                if os.path.isdir(local_path):
                    dir_success_count = 0
                    dir_fail_count = 0
                    
                    # 1. Determine Drive parent for the ROOT of this directory
                    drive_parent_parts = [p for p in relative_path_for_drive.parts if p != '.'][:-1]
                    base_drive_parent_id = provider_root_id
                    if drive_parent_parts:
                        base_drive_parent_id = folder_provider.ensure_folder_path(drive_parent_parts, root_id=provider_root_id)

                    # 2. Walk the directory
                    # We want the folder itself to exist in Drive.
                    folder_name = relative_path_for_drive.name
                    # Ensure the folder itself exists
                    root_folder_id = folder_provider.ensure_folder_path([folder_name], root_id=base_drive_parent_id)

                    for root, dirs, files in os.walk(local_path):
                        for file in files:
                            full_file_path = Path(root) / file
                            # Relative path from the directory being backed up
                            rel_from_root = full_file_path.relative_to(local_path)
                            
                            try:
                                # Determine sub-folder structure in Drive
                                file_parent_parts = list(rel_from_root.parts)[:-1]
                                current_file_parent_id = root_folder_id
                                if file_parent_parts:
                                    current_file_parent_id = folder_provider.ensure_folder_path(file_parent_parts, root_id=root_folder_id)
                                
                                # MD5 Check
                                remote_file = folder_provider.find_file(file, parent_id=current_file_parent_id)
                                if remote_file and remote_file.get('md5Checksum'):
                                    local_md5 = get_local_md5(full_file_path)
                                    if local_md5 == remote_file['md5Checksum']:
                                        dir_success_count += 1
                                        continue
                                
                                folder_provider.sync_file(full_file_path, current_file_parent_id, name=file)
                                dir_success_count += 1
                                
                            except Exception as e:
                                dir_fail_count += 1
                                items.append(BackupItemResult(str(rel_from_root), BackupStatus.FAILED, f"In dir scan: {e}", type="Home"))
                    
                    status_msg = f"Synced dir: {dir_success_count} files"
                    if dir_fail_count > 0:
                        status_msg += f" ({dir_fail_count} failed)"
                    items.append(BackupItemResult(rel_path, BackupStatus.SUCCESS, status_msg, type="Home"))
                    success_count += 1
                    continue

                # Single File Logic (Existing)
                try:
                    drive_parent_parts = [p for p in relative_path_for_drive.parts if p != '.'][:-1]
                    file_name_for_drive = Path(rel_path).name
                    
                    current_drive_parent_id = provider_root_id
                    if drive_parent_parts:
                        current_drive_parent_id = folder_provider.ensure_folder_path(drive_parent_parts, root_id=provider_root_id)
                    
                    # MD5 Check
                    remote_file = folder_provider.find_file(file_name_for_drive, parent_id=current_drive_parent_id)
                    if remote_file and remote_file.get('md5Checksum'):
                        local_md5 = get_local_md5(local_path)
                        if local_md5 == remote_file['md5Checksum']:
                            items.append(BackupItemResult(rel_path, BackupStatus.NO_CHANGE, "No change (MD5 match)", type="Home"))
                            continue
                    
                    folder_provider.sync_file(local_path, current_drive_parent_id, name=file_name_for_drive)
                    items.append(BackupItemResult(rel_path, BackupStatus.SUCCESS, "Synced", type="Home"))
                    success_count += 1
                    
                except Exception as e:
                    items.append(BackupItemResult(rel_path, BackupStatus.FAILED, str(e), type="Home"))
            
            return ProviderResult(self.name, "success", f"Backed up {success_count} files", items)
        except Exception as e:
            return ProviderResult(self.name, "failure", str(e), items)

import os
import subprocess
import hashlib
import sys
import tempfile
import shutil
from typing import Dict, Any, List
from agentic_consult.backup.providers.base import BackupProvider
from agentic_consult.backup.folder_providers.factory import get_folder_provider
from agentic_consult.config import get_backups_google_drive_folder_id
from agentic_consult.backup.results import ProviderResult, BackupItemResult, BackupStatus

class LocalRepoBackup(BackupProvider):
    @property
    def name(self) -> str:
        return "Local-Only Git Repositories"

    def run(self, config: Dict[str, Any], options: Dict[str, Any]) -> ProviderResult:
        local_repos_config = config.get('backups', {}).get('local_repos', {})
        enabled = local_repos_config.get('enabled', True)
        
        if not enabled:
            return ProviderResult(self.name, "skipped", "Provider disabled in configuration", [])

        ws_dir = local_repos_config.get('path')
        if not ws_dir:
             return ProviderResult(self.name, "failure", "Configuration missing: backups.local_repos.path is required.", [])
        
        ws_dir = os.path.expanduser(ws_dir)

        folder_provider = get_folder_provider()
        items = []
        target_folder_id = get_backups_google_drive_folder_id()
        if not target_folder_id:
             return ProviderResult(self.name, "failure", "Backup folder not configured.", [])
        
        try:
             provider_folder_id = folder_provider.ensure_folder_path(["local-only-repos"], root_id=target_folder_id)
        except Exception as e:
             return ProviderResult(self.name, "failure", f"Could not access 'local-only-repos': {e}", [])

        if not os.path.exists(ws_dir):
            return ProviderResult(self.name, "skipped", f"Directory {ws_dir} not found", [])

        repos_to_backup = self._find_local_repos(ws_dir)
        if not repos_to_backup:
            return ProviderResult(self.name, "success", "No local-only repositories found", [])

        temp_dir = tempfile.mkdtemp(prefix="consult_backups_")
        try:
            for repo_path in repos_to_backup:
                item_result = self.backup_single_repo(
                    repo_path=repo_path,
                    folder_provider=folder_provider,
                    provider_folder_id=provider_folder_id,
                    temp_dir=temp_dir,
                    options=options
                )
                items.append(item_result)
                if item_result.status == BackupStatus.FAILED:
                    return ProviderResult(self.name, "failure", item_result.message, items)

            success_count = len([i for i in items if i.status == BackupStatus.SUCCESS])
            return ProviderResult(self.name, "success", f"Backed up {success_count} repositories", items)
            
        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

    def backup_single_repo(self, repo_path: str, folder_provider, provider_folder_id: str, temp_dir: str, options: Dict[str, Any]) -> BackupItemResult:
        """Handles the backup logic for a single repository."""
        import click 

        repo_name = os.path.basename(repo_path)
        force = options.get('force', False)
        skip_dirty = options.get('skip_dirty', False)
        interactive = options.get('interactive', True)

        # Dirty Check
        if self._is_dirty(repo_path):
            stats = self._get_git_status_stats(repo_path)
            dirty_details = f"Staged: {stats['staged']}, Unstaged: {stats['unstaged']}, Untracked: {stats['untracked']}"
            
            if interactive and not force and not skip_dirty:
                click.echo(f"\nRepository '{repo_name}' is dirty.\n  - {dirty_details}", err=True)
                if not click.confirm(f"Do you want to backup ONLY committed changes for '{repo_name}'?"):
                    return BackupItemResult(repo_name, BackupStatus.DIRTY, "Skipped (dirty)", type="Repo")
            else:
                if skip_dirty:
                    return BackupItemResult(repo_name, BackupStatus.DIRTY, "Skipped (dirty)", type="Repo")
                if not force:
                    return BackupItemResult(repo_name, BackupStatus.FAILED, f"Dirty: {dirty_details}", type="Repo")
                else: # force=True
                    print(f"Warning: {repo_name} is dirty. Backing up committed code only.", file=sys.stderr)
        
        current_hash = self._get_repo_state_hash(repo_path)
        bundle_filename = f"{repo_name}.bundle"
        remote_file = folder_provider.find_file(bundle_filename, provider_folder_id)
        
        last_hash = remote_file['appProperties'].get('state_hash') if remote_file and 'appProperties' in remote_file else None
        
        verb = "updated" if remote_file else "added"

        if current_hash == last_hash and remote_file:
            return BackupItemResult(repo_name, BackupStatus.NO_CHANGE, "No new commits", type="Repo")

        bundle_path = os.path.join(temp_dir, bundle_filename)
        print(f"Bundling {repo_name}...", file=sys.stderr)
        try:
            subprocess.run(["git", "bundle", "create", bundle_path, "--all"], cwd=repo_path, check=True, capture_output=True)
            
            sync_result = folder_provider.sync_file(
                bundle_path, 
                provider_folder_id, 
                name=bundle_filename, 
                app_properties={'state_hash': current_hash}
            )
            
            file_id = sync_result.get('id', 'unknown')
            msg = f"COMPLETED ({verb} {bundle_filename} on Google Drive as {file_id})"
            
            return BackupItemResult(repo_name, BackupStatus.SUCCESS, msg, type="Repo")
        except subprocess.CalledProcessError as e:
            return BackupItemResult(repo_name, BackupStatus.FAILED, f"Bundle failed: {e.stderr.decode().strip()}", type="Repo")
        finally:
            if os.path.exists(bundle_path):
                os.remove(bundle_path)

    def _find_local_repos(self, root_dir: str) -> List[str]:
        # ... (rest of the file is the same)
        local_repos = []
        for root, dirs, files in os.walk(root_dir):
            if ".git" in dirs:
                repo_path = root
                if not self._has_remotes(repo_path):
                    local_repos.append(repo_path)
                dirs.remove(".git")
        return local_repos

    def _has_remotes(self, repo_path: str) -> bool:
        try:
            result = subprocess.run(["git", "remote"], cwd=repo_path, capture_output=True, text=True, check=True)
            return bool(result.stdout.strip())
        except Exception: return False

    def _is_dirty(self, repo_path: str) -> bool:
        try:
            result = subprocess.run(["git", "status", "--porcelain"], cwd=repo_path, capture_output=True, text=True, check=True)
            return bool(result.stdout.strip())
        except Exception: return False

    def _get_git_status_stats(self, repo_path: str) -> Dict[str, int]:
        stats = {'staged': 0, 'unstaged': 0, 'untracked': 0, 'ignored': 0}
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain", "--ignored"], 
                cwd=repo_path, capture_output=True, text=True, check=True
            )
            for line in result.stdout.splitlines():
                if not line: continue
                x, y = line[0], line[1]
                if x == '?' and y == '?': stats['untracked'] += 1
                elif x == '!' and y == '!': stats['ignored'] += 1
                else:
                    if x not in [' ', '?', '!']: stats['staged'] += 1
                    if y not in [' ', '?', '!']: stats['unstaged'] += 1
        except Exception: pass
        return stats

    def _get_repo_state_hash(self, repo_path: str) -> str:
        try:
            result = subprocess.run(["git", "show-ref"], cwd=repo_path, capture_output=True, text=True)
            return hashlib.md5(result.stdout.encode()).hexdigest()
        except Exception: return ""

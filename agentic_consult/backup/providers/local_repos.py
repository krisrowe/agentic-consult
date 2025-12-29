import os
import subprocess
import shutil
import sys
import tempfile
from typing import Dict, Any, List
from agentic_consult.backup.providers.git_base import GitBaseProvider
from agentic_consult.backup.folder_providers.factory import get_folder_provider
from agentic_consult.config import get_backups_google_drive_folder_id
from agentic_consult.backup.results import ProviderResult, BackupItemResult, BackupStatus

class LocalRepoBackup(GitBaseProvider):
    @property
    def name(self) -> str:
        return "Local-Only Git Repositories"

    def run(self, config: Dict[str, Any], options: Dict[str, Any]) -> ProviderResult:
        ws_dir = self._get_workspace_path(config)
        if not ws_dir:
             return ProviderResult(self.name, "failure", "Configuration missing: backups.local_repos.path is required.", [])
        
        # Check enabled status (specific to local repos logic if needed, but usually strictly by config presence)
        local_repos_config = config.get('backups', {}).get('local_repos', {})
        if not local_repos_config.get('enabled', True):
             return ProviderResult(self.name, "skipped", "Provider disabled", [])

        if not os.path.exists(ws_dir):
            return ProviderResult(self.name, "skipped", f"Directory {ws_dir} not found", [])

        folder_provider = get_folder_provider()
        target_folder_id = get_backups_google_drive_folder_id()
        if not target_folder_id:
             return ProviderResult(self.name, "failure", "Backup folder not configured.", [])

        # In dry-run, we might not need to ensure folder path exists if we just want to see what *would* happen locally?
        # But to check if file exists (hash check), we need to read from Drive.
        # So we must access Drive.
        try:
             provider_folder_id = folder_provider.ensure_folder_path(["local-only-repos"], root_id=target_folder_id)
        except Exception as e:
             return ProviderResult(self.name, "failure", f"Could not access 'local-only-repos': {e}", [])

        repos = self._find_repos(ws_dir)
        items = []
        
        # Filter for local-only
        local_repos = [r for r in repos if not self._has_remotes(r)]

        if not local_repos:
            return ProviderResult(self.name, "success", "No local-only repositories found", [])

        temp_dir = tempfile.mkdtemp(prefix="consult_backups_")
        try:
            for repo_path in local_repos:
                item_result = self.backup_single_repo(
                    repo_path=repo_path,
                    folder_provider=folder_provider,
                    provider_folder_id=provider_folder_id,
                    temp_dir=temp_dir,
                    options=options
                )
                items.append(item_result)
                
                # In backup all flow, we usually continue on failure, but update status.

            success_count = len([i for i in items if i.status in [BackupStatus.SUCCESS, BackupStatus.NO_CHANGE, BackupStatus.PENDING]])
            return ProviderResult(self.name, "success", f"Processed {len(items)} repositories", items)
            
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
        dry_run = options.get('dry_run', False)

        # Dirty Check
        if self._is_dirty(repo_path):
            stats = self._get_git_status_stats(repo_path)
            # Only show non-zero counts
            p = []
            if stats['staged'] > 0: p.append(f"Staged: {stats['staged']}")
            if stats['unstaged'] > 0: p.append(f"Unstaged: {stats['unstaged']}")
            if stats['untracked'] > 0: p.append(f"Untracked: {stats['untracked']}")
            dirty_msg = ", ".join(p) if p else "Dirty"
            
            # Interactive prompt logic
            if interactive and not force and not skip_dirty and not dry_run:
                click.echo(f"\nRepository '{repo_name}' is dirty.\n  - {dirty_msg}", err=True)
                if not click.confirm(f"Do you want to backup ONLY committed changes for '{repo_name}'?"):
                    return BackupItemResult(repo_name, BackupStatus.DIRTY, "Skipped (dirty)", type="Local Repo", details={'stats': stats})
            else:
                if skip_dirty:
                    return BackupItemResult(repo_name, BackupStatus.DIRTY, "Skipped (dirty)", type="Local Repo", details={'stats': stats})
                if not force:
                    # In dry run, report that it IS dirty and thus would fail/skip
                    return BackupItemResult(repo_name, BackupStatus.DIRTY, dirty_msg, type="Local Repo", details={'stats': stats})
                else: 
                    # force=True, proceed (warn if not quiet)
                    if not dry_run:
                        print(f"Warning: {repo_name} is dirty. Backing up committed code only.", file=sys.stderr)
        
        current_hash = self._get_repo_state_hash(repo_path)
        bundle_filename = f"{repo_name}.bundle"
        remote_file = folder_provider.find_file(bundle_filename, provider_folder_id)
        
        last_hash = remote_file['appProperties'].get('state_hash') if remote_file and 'appProperties' in remote_file else None
        
        verb = "update" if remote_file else "add"

        if current_hash == last_hash and remote_file:
            return BackupItemResult(repo_name, BackupStatus.NO_CHANGE, "No new commits", type="Local Repo")

        if dry_run:
            return BackupItemResult(repo_name, BackupStatus.PENDING, f"Would {verb} backup", type="Local Repo")

        # Actual Backup Action
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
            
            past_verb = "updated" if verb == "update" else "added"
            msg = f"{past_verb.capitalize()} {bundle_filename}"
            
            return BackupItemResult(repo_name, BackupStatus.SUCCESS, msg, type="Local Repo")
        except subprocess.CalledProcessError as e:
            return BackupItemResult(repo_name, BackupStatus.FAILED, f"Bundle failed: {e.stderr.decode().strip()}", type="Local Repo")
        finally:
            if os.path.exists(bundle_path):
                os.remove(bundle_path)


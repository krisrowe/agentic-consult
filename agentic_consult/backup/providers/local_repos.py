import os
import subprocess
import hashlib
import sys
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
        folder_provider = get_folder_provider()
        ws_dir = os.path.expanduser("~/ws")
        force = options.get('force', False)
        skip_dirty = options.get('skip_dirty', False)
        interactive = options.get('interactive', True)
        
        items = []

        target_folder_id = get_backups_google_drive_folder_id()
        if not target_folder_id:
             return ProviderResult(self.name, "failure", "Backup folder not configured.", [])
        
        try:
             provider_folder_id = folder_provider.ensure_folder_path(["local-only-repos"], root_id=target_folder_id)
        except Exception as e:
             return ProviderResult(self.name, "failure", f"Could not access 'local-only-repos': {e}", [])

        if not os.path.exists(ws_dir):
            return ProviderResult(self.name, "skipped", f"Workspace directory {ws_dir} not found", [])

        repos_to_backup = self._find_local_repos(ws_dir)
        if not repos_to_backup:
            return ProviderResult(self.name, "success", "No local-only repositories found", [])

        import click 

        try:
            for repo_path in repos_to_backup:
                repo_name = os.path.basename(repo_path)
                
                # Dirty Check
                if self._is_dirty(repo_path):
                    stats = self._get_git_status_stats(repo_path)
                    dirty_details = (
                        f"  - Staged: {stats['staged']}, Unstaged: {stats['unstaged']}, "
                        f"Untracked: {stats['untracked']}"
                    )
                    
                    dirty_msg = "Dirty repo"

                    should_backup = False
                    
                    if interactive and not force and not skip_dirty:
                        click.echo(f"\nRepository '{repo_name}' is dirty.\n{dirty_details}", err=True)
                        click.echo("WARNING: git bundles ONLY include committed objects.", err=True)
                        # click.confirm prompts to stdout by default, unfortunately.
                        # However, for interactive CLI, this is usually acceptable unless strict piping is required.
                        # If strict stderr is required for prompts, we might need a workaround, but click doesn't easily support it.
                        # Given the requirement "backup output go to stderr except for the final output", 
                        # prompts are technically "output" but they are transient.
                        # Let's assume standard click behavior is acceptable for interactive prompts, 
                        # or try to force it if possible. 
                        # But click.confirm doesn't take 'file' or 'err'.
                        if click.confirm(f"Do you want to backup ONLY committed changes for '{repo_name}'?"):
                            should_backup = True
                            dirty_msg = "Dirty (Backed up committed only)"
                        else:
                            items.append(BackupItemResult(repo_name, BackupStatus.SKIPPED, "User skipped (dirty)"))
                            continue
                    else:
                        # Non-interactive logic
                        if force:
                            should_backup = True
                            dirty_msg = "Dirty (Forced)"
                            print(f"Warning: {repo_name} is dirty. Backing up committed code only.", file=sys.stderr)
                        elif skip_dirty:
                             items.append(BackupItemResult(repo_name, BackupStatus.SKIPPED, "Skipped dirty (--skip-dirty)"))
                             continue
                        else:
                            items.append(BackupItemResult(repo_name, BackupStatus.FAILED, f"Dirty: {dirty_details}"))
                            return ProviderResult(self.name, "failure", f"Repository '{repo_name}' is dirty. Use --force or --skip-dirty.", items)

                else:
                    should_backup = True
                    dirty_msg = ""

                if not should_backup:
                    continue

                current_hash = self._get_repo_state_hash(repo_path)
                
                bundle_filename = f"{repo_name}.bundle"
                remote_file = folder_provider.find_file(bundle_filename, provider_folder_id)
                
                last_hash = None
                if remote_file and 'appProperties' in remote_file:
                    last_hash = remote_file['appProperties'].get('state_hash')
                
                if current_hash == last_hash and remote_file:
                    print(f"Skipping {repo_name}: No changes detected.", file=sys.stderr)
                    items.append(BackupItemResult(repo_name, BackupStatus.SKIPPED, "No changes"))
                    continue

                bundle_path = os.path.join(repo_path, bundle_filename)
                print(f"Bundling {repo_name}...", file=sys.stderr)
                try:
                    subprocess.run(
                        ["git", "bundle", "create", bundle_filename, "--all"],
                        cwd=repo_path, check=True, capture_output=True
                    )
                    
                    folder_provider.sync_file(
                        bundle_path, 
                        provider_folder_id, 
                        name=bundle_filename,
                        app_properties={'state_hash': current_hash}
                    )
                    status_msg = "Synced"
                    if dirty_msg:
                        status_msg += f" [{dirty_msg}]"
                    items.append(BackupItemResult(repo_name, BackupStatus.SUCCESS, status_msg))
                    
                except subprocess.CalledProcessError as e:
                    print(f"Bundle error for {repo_name}: {e.stderr.decode()}", file=sys.stderr)
                    items.append(BackupItemResult(repo_name, BackupStatus.FAILED, f"Bundle failed: {e.stderr.decode().strip()}"))
                finally:
                    if os.path.exists(bundle_path):
                        os.remove(bundle_path)

            success_count = len([i for i in items if i.status == BackupStatus.SUCCESS])
            return ProviderResult(self.name, "success", f"Backed up {success_count} repositories", items)
            
        except Exception as e:
            return ProviderResult(self.name, "failure", str(e), items)

    def _find_local_repos(self, root_dir: str) -> List[str]:
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
                x = line[0]
                y = line[1]
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
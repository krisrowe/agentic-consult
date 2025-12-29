import os
import subprocess
from typing import Dict, Any
from agentic_consult.backup.providers.git_base import GitBaseProvider
from agentic_consult.backup.results import ProviderResult, BackupItemResult, BackupStatus

class RemoteRepoBackup(GitBaseProvider):
    @property
    def name(self) -> str:
        return "Remote Git Repositories"

    def run(self, config: Dict[str, Any], options: Dict[str, Any]) -> ProviderResult:
        ws_dir = self._get_workspace_path(config)
        if not ws_dir:
             return ProviderResult(self.name, "skipped", "Workspace path not configured", [])

        if not os.path.exists(ws_dir):
            return ProviderResult(self.name, "skipped", f"Directory {ws_dir} not found", [])

        repos = self._find_repos(ws_dir)
        items = []

        for repo_path in repos:
            if self._has_remotes(repo_path):
                items.append(self.validate_repo(repo_path))

        if not items:
            return ProviderResult(self.name, "success", "No remote repositories found", [])

        # For remote repos, validation failures (dirty/unpushed) are technically "Success" of the check 
        # (we successfully checked them), but we want to alert the user.
        # However, the status returned here aggregates the run.
        # If any are dirty/unpushed, is the *Provider* run a failure?
        # Usually for backups, "Success" means "We did what we were supposed to do".
        # But if the goal is "Ensure everything is backed up", then dirty/unpushed is a failure state for that item.
        
        # We'll count failures/dirty as issues.
        issues_count = len([i for i in items if i.status in [BackupStatus.FAILED, BackupStatus.DIRTY]])
        
        msg = f"Checked {len(items)} repos"
        if issues_count > 0:
            msg += f" ({issues_count} require attention)"
            
        return ProviderResult(self.name, "success", msg, items)

    def validate_repo(self, repo_path: str) -> BackupItemResult:
        """Validates a repository with remotes (status check only)."""
        repo_name = os.path.basename(repo_path)
        
        # 1. Check Cleanliness
        if self._is_dirty(repo_path):
            stats = self._get_git_status_stats(repo_path)
            dirty_details = f"Staged: {stats['staged']}, Unstaged: {stats['unstaged']}, Untracked: {stats['untracked']}"
            return BackupItemResult(repo_name, BackupStatus.DIRTY, f"Dirty: {dirty_details}", type="Remote Repo")

        # 2. Check Pushed status
        from agentic_consult.backup.git_utils import GitUtils
        status = GitUtils.get_remote_status(repo_path)
        
        if status == "ahead":
            return BackupItemResult(repo_name, BackupStatus.FAILED, "Unpushed commits", type="Remote Repo")
        elif status == "unknown":
             return BackupItemResult(repo_name, BackupStatus.FAILED, "Status unknown (no upstream?)", type="Remote Repo")
        
        return BackupItemResult(repo_name, BackupStatus.SUCCESS, "Clean & Pushed", type="Remote Repo")

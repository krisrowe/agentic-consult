import os
import subprocess
import hashlib
from typing import Dict, Any, List
from agentic_consult.backup.providers.base import BackupProvider
from agentic_consult.backup.results import ProviderResult, BackupItemResult, BackupStatus
from agentic_consult.backup.git_utils import GitUtils

class GitBaseProvider(BackupProvider):
    @property
    def config_key(self) -> str:
        return 'local_repos'  # Can be overridden or made more generic

    def _get_workspace_path(self, config: Dict[str, Any]) -> str:
        local_repos_config = config.get('backups', {}).get(self.config_key, {})
        ws_dir = local_repos_config.get('path')
        if ws_dir:
            return os.path.expanduser(ws_dir)
        return None

    def _find_repos(self, root_dir: str) -> List[str]:
        repos = []
        for root, dirs, files in os.walk(root_dir):
            if ".git" in dirs:
                repos.append(root)
                # Don't recurse into .git
                dirs.remove(".git")
        return repos

    def _has_remotes(self, repo_path: str) -> bool:
        return GitUtils.has_remotes(repo_path)

    def _is_dirty(self, repo_path: str) -> bool:
        return GitUtils.is_dirty(repo_path)

    def _get_git_status_stats(self, repo_path: str) -> Dict[str, int]:
        return GitUtils.get_status_stats(repo_path)

    def _get_repo_state_hash(self, repo_path: str) -> str:
        return GitUtils.get_repo_state_hash(repo_path)

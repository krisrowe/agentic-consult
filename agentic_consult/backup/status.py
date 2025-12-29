import os
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from agentic_consult.backup.git_utils import GitUtils
from agentic_consult.backup.folder_providers.factory import get_folder_provider
from agentic_consult.config import get_backups_google_drive_folder_id

@dataclass
class RepoStatus:
    path: str
    name: str
    is_git: bool
    type: str  # "Local-Only" or "Remote"
    backup_needed: bool
    status: str # "Clean", "Dirty", "Unpushed", "Pending Backup", "Backed Up", "Error"
    guidance: str
    details: Dict[str, Any]

def assess_repo_status(path: str, dry_run: bool = False) -> RepoStatus:
    """
    Assesses the status of a git repository for backup purposes.
    dry_run: If True, assumes non-interactive and only reports status (no side effects).
    """
    abs_path = os.path.abspath(path)
    name = os.path.basename(abs_path)
    
    if not GitUtils.is_git_repo(abs_path):
        return RepoStatus(
            path=abs_path,
            name=name,
            is_git=False,
            type="Unknown",
            backup_needed=False,
            status="Not a git repo",
            guidance="Initialize git or check path.",
            details={}
        )

    has_remotes = GitUtils.has_remotes(abs_path)
    repo_type = "Remote" if has_remotes else "Local-Only"
    
    stats = GitUtils.get_status_stats(abs_path)
    is_dirty = stats['staged'] > 0 or stats['unstaged'] > 0
    
    details = {
        'has_remotes': has_remotes,
        'dirty_stats': stats
    }

    if repo_type == "Remote":
        remote_status = GitUtils.get_remote_status(abs_path)
        details['remote_status'] = remote_status
        
        if is_dirty:
            return RepoStatus(
                path=abs_path,
                name=name,
                is_git=True,
                type=repo_type,
                backup_needed=True, # Needs push
                status="Dirty",
                guidance="Commit changes and push to remote.",
                details=details
            )
        
        if remote_status == "ahead":
            return RepoStatus(
                path=abs_path,
                name=name,
                is_git=True,
                type=repo_type,
                backup_needed=True,
                status="Unpushed",
                guidance="Push commits to remote.",
                details=details
            )
            
        return RepoStatus(
            path=abs_path,
            name=name,
            is_git=True,
            type=repo_type,
            backup_needed=False,
            status="Clean & Pushed",
            guidance="Repository is safe on remote.",
            details=details
        )
        
    else: # Local-Only
        # Check against Drive
        try:
            folder_id = get_backups_google_drive_folder_id()
            if not folder_id:
                return RepoStatus(
                    path=abs_path,
                    name=name,
                    is_git=True,
                    type=repo_type,
                    backup_needed=True,
                    status="Config Error",
                    guidance="Configure backup folder ID to enable status checks.",
                    details=details
                )
            
            folder_provider = get_folder_provider()
            # We assume "local-only-repos" structure
            # To avoid creating folders just for a status check, we should try to find it first.
            # But ensure_folder_path is what providers use. 
            # If checking status, we might not want to create the folder if it doesn't exist?
            # Existing code: provider_folder_id = folder_provider.ensure_folder_path(["local-only-repos"]...)
            # We'll stick to that for consistency, or handle the error if not found.
            
            # Optimization: Try to find 'local-only-repos' first without ensure?
            # folder_provider interface only has find_folder (single level).
            # Let's trust ensure_folder_path is relatively cheap or we accept it.
            # Actually, `LocalRepoBackup` creates it.
            
            local_repos_folder_id = folder_provider.find_folder("local-only-repos", parent_id=folder_id)
            
            if not local_repos_folder_id:
                 return RepoStatus(
                    path=abs_path,
                    name=name,
                    is_git=True,
                    type=repo_type,
                    backup_needed=True,
                    status="No Backup Folder",
                    guidance="Run 'consult backup all' to initialize backups.",
                    details=details
                )
            
            bundle_filename = f"{name}.bundle"
            remote_file = folder_provider.find_file(bundle_filename, local_repos_folder_id)
            
            current_hash = GitUtils.get_repo_state_hash(abs_path)
            details['current_hash'] = current_hash
            
            if remote_file:
                last_hash = remote_file.get('appProperties', {}).get('state_hash')
                details['remote_hash'] = last_hash
                
                if current_hash == last_hash:
                    return RepoStatus(
                        path=abs_path,
                        name=name,
                        is_git=True,
                        type=repo_type,
                        backup_needed=False,
                        status="Backed Up",
                        guidance="No action needed.",
                        details=details
                    )
                else:
                    if is_dirty:
                         return RepoStatus(
                            path=abs_path,
                            name=name,
                            is_git=True,
                            type=repo_type,
                            backup_needed=True,
                            status="Dirty & Outdated",
                            guidance="Commit changes and run 'consult backup local-repo' or 'consult backup all'.",
                            details=details
                        )
                    return RepoStatus(
                        path=abs_path,
                        name=name,
                        is_git=True,
                        type=repo_type,
                        backup_needed=True,
                        status="Outdated Backup",
                        guidance="Run 'consult backup local-repo' or 'consult backup all' to update.",
                        details=details
                    )
            else:
                 return RepoStatus(
                    path=abs_path,
                    name=name,
                    is_git=True,
                    type=repo_type,
                    backup_needed=True,
                    status="Not Backed Up",
                    guidance="Run 'consult backup local-repo' or 'consult backup all' to create initial backup.",
                    details=details
                )
                
        except Exception as e:
             return RepoStatus(
                path=abs_path,
                name=name,
                is_git=True,
                type=repo_type,
                backup_needed=True, # Assume true on error
                status="Check Error",
                guidance=f"Error checking status: {str(e)}",
                details={'error': str(e)}
            )

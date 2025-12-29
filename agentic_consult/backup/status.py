import os
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from agentic_consult.backup.git_utils import GitUtils
from agentic_consult.backup.folder_providers.factory import get_folder_provider
from agentic_consult.config import get_backups_google_drive_folder_id

@dataclass
class RepoStatus:
    path: str
    local: Dict[str, Any]
    remote: Dict[str, Any]
    summary: Dict[str, Any]

def assess_repo_status(path: str, dry_run: bool = False) -> RepoStatus:
    """
    Assesses the status of a git repository for backup purposes.
    dry_run: If True, assumes non-interactive and only reports status (no side effects).
    """
    abs_path = os.path.abspath(path)
    name = os.path.basename(abs_path)
    
    if not GitUtils.is_git_repo(abs_path):
        summary = {
            "name": name,
            "type": "Unknown",
            "status": "Not a git repo",
            "guidance": "Initialize git or check path.",
            "is_git": False,
            "backup_needed": False
        }
        return RepoStatus(
            path=abs_path,
            local={"status": "UNKNOWN", "stats": {}},
            remote={"status": "UNKNOWN", "stats": {}},
            summary=summary
        )

    has_remotes = GitUtils.has_remotes(abs_path)
    repo_type = "Remote" if has_remotes else "Local-Only"
    
    stats = GitUtils.get_status_stats(abs_path)
    is_dirty = stats['staged'] > 0 or stats['unstaged'] > 0
    
    local = {
        'status': "DIRTY" if is_dirty else "CLEAN",
        'stats': stats
    }

    remote = {"status": "UNDEFINED", "stats": {}}
    backup_needed = False
    status_msg = "Clean"
    guidance = "No action needed."

    if repo_type == "Remote":
        remote_info = GitUtils.get_remote_status(abs_path)
        remote_status = remote_info['status']
        last_fetch = GitUtils.get_last_fetch_time(abs_path)
        
        # Map to uppercase Enum-like strings for the relationship
        remote_enum_map = {
            'clean': 'SYNCED',
            'ahead': 'AHEAD',
            'behind': 'BEHIND',
            'diverged': 'DIVERGED',
            'unknown': 'UNKNOWN'
        }
        
        remote = {
            'status': remote_enum_map.get(remote_status, 'UNKNOWN'),
            'last_fetch': last_fetch,
            'stats': {
                'unpushed': remote_info.get('unpushed', 0),
                'unpulled': remote_info.get('unpulled', 0)
            }
        }
        
        if is_dirty:
            backup_needed = True
            status_msg = "Dirty"
            guidance = "Commit changes and push to remote."
        elif remote_status == "ahead":
            backup_needed = True
            status_msg = "Unpushed"
            guidance = "Push commits to remote."
        elif remote_status == "diverged":
            backup_needed = True
            status_msg = "Diverged"
            guidance = "Repository has both unpushed and unpulled commits. Manual merge required."
        elif remote_status == "behind":
            status_msg = "Behind"
            guidance = "Pull latest changes from remote."
        elif remote_status == "clean":
            status_msg = "Clean & Pushed"
            guidance = "Repository is safe on remote."
        
    else: # Local-Only
        try:
            folder_id = get_backups_google_drive_folder_id()
            if not folder_id:
                status_msg = "Config Error"
                guidance = "Configure backup folder ID to enable status checks."
                backup_needed = True
            else:
                folder_provider = get_folder_provider()
                local_repos_folder_id = folder_provider.find_folder("local-only-repos", parent_id=folder_id)
                
                if not local_repos_folder_id:
                    status_msg = "No Backup Folder"
                    guidance = "Run 'consult backup all' to initialize backups."
                    backup_needed = True
                else:
                    bundle_filename = f"{name}.bundle"
                    remote_file = folder_provider.find_file(bundle_filename, local_repos_folder_id)
                    current_hash = GitUtils.get_repo_state_hash(abs_path)
                    
                    if remote_file:
                        last_hash = remote_file.get('appProperties', {}).get('state_hash')
                        is_synced = current_hash == last_hash
                        
                        remote = {
                            'status': 'SYNCED' if is_synced else 'OUTDATED',
                            'stats': {
                                'local_hash': current_hash,
                                'remote_hash': last_hash
                            }
                        }
                        
                        if is_synced:
                            status_msg = "Backed Up"
                            guidance = "No action needed."
                        else:
                            backup_needed = True
                            if is_dirty:
                                status_msg = "Dirty & Outdated"
                                guidance = "Commit changes and run 'consult backup local-repo' or 'consult backup all'."
                            else:
                                status_msg = "Outdated Backup"
                                guidance = "Run 'consult backup local-repo' or 'consult backup all' to update."
                    else:
                        remote = {
                            'status': 'UNDEFINED',
                            'stats': {
                                'local_hash': current_hash,
                                'remote_hash': None
                            }
                        }
                        backup_needed = True
                        status_msg = "Not Backed Up"
                        guidance = "Run 'consult backup local-repo' or 'consult backup all' to create initial backup."
                
        except Exception as e:
            backup_needed = True
            status_msg = "Check Error"
            guidance = f"Error checking status: {str(e)}"
            remote = {"status": "ERROR", "stats": {"error": str(e)}}

    summary = {
        "name": name,
        "type": repo_type,
        "status": status_msg,
        "guidance": guidance,
        "is_git": True,
        "backup_needed": backup_needed
    }

    return RepoStatus(
        path=abs_path,
        local=local,
        remote=remote,
        summary=summary
    )

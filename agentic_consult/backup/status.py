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
    identity: Dict[str, Any]

def _resolve_identity(path: str, history_stats: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolves identity based on strict history matching rules:
    - First commit matches
    - Last N commits match (default 10)
    - Total % matches (default 90%)
    """
    # Load config thresholds
    from agentic_consult.config import load_app_config
    app_config = load_app_config()
    workspace_analysis = app_config.get('workspace_analysis', {})
    required_n = workspace_analysis.get('required_last_commits_match', 10)
    required_percent = workspace_analysis.get('required_total_match_percent', 90)

    detected_email = None
    source = "Unresolved"
    confidence = "None" # High, Medium, Low, None

    first = history_stats.get('first_commit_author')
    last_n = history_stats.get('last_n_authors', [])
    total_count = history_stats.get('total_commit_count', 0)
    author_counts = history_stats.get('author_counts', {})
    
    # Logic:
    # 1. Check if history is sufficient for N check
    # If total < required_n, check all commits (must be 100% same)
    
    candidate = None
    
    if total_count > 0:
        # Find dominant author
        sorted_authors = sorted(author_counts.items(), key=lambda x: x[1], reverse=True)
        dominant_email, dominant_count = sorted_authors[0]
        percent = (dominant_count / total_count) * 100
        
        # Check Rules
        # Rule A: First commit matches dominant
        first_matches = (first == dominant_email)
        
        # Rule B: Last N matches dominant (or all if total < N)
        if total_count < required_n:
            last_n_matches = all(e == dominant_email for e in last_n)
        else:
            # Check only the last N entries
            last_n_matches = all(e == dominant_email for e in last_n[:required_n])
            
        # Rule C: Percent threshold
        percent_matches = percent >= required_percent
        
        if first_matches and last_n_matches and percent_matches:
            detected_email = dominant_email
            source = f"History (First + Last {len(last_n)} + {int(percent)}%)"
            confidence = "High"
        else:
             # Fallback: Just report stats but don't confirm identity
             source = f"Mixed History (Dom: {int(percent)}%)"
    
    # Check Git Config (Override/Supplement)
    git_config_email = GitUtils.get_config(path, "user.email")
    if git_config_email:
        if not detected_email:
            detected_email = git_config_email
            source = "Git Config"
            confidence = "Medium"
        elif detected_email != git_config_email:
            # Conflict
            detected_email = git_config_email
            source = "Git Config (Overrides History)"
            confidence = "Medium"

    return {
        "email": detected_email,
        "source": source,
        "confidence": confidence,
        "stats": history_stats
    }

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
            "classification": "Unknown",
            "status": "Not a git repo",
            "guidance": "Initialize git or check path.",
            "is_git": False,
            "backup_needed": False
        }
        return RepoStatus(
            path=abs_path,
            local={"status": "UNKNOWN", "stats": {}},
            remote={"status": "UNKNOWN", "stats": {}},
            summary=summary,
            identity={"email": None, "source": "N/A", "confidence": "None", "stats": {}}
        )

    has_remotes = GitUtils.has_remotes(abs_path)
    remote_url = GitUtils.get_remote_url(abs_path) if has_remotes else None
    repo_type = "Remote" if has_remotes else "Local-Only"
    
    classification = "Local-Only"
    if has_remotes and remote_url:
        if "github.com" in remote_url:
            classification = "GitHub"
        else:
            classification = "Remote"

    # Load thresholds for history stats
    from agentic_consult.config import load_app_config
    app_config = load_app_config()
    required_n = app_config.get('workspace_analysis', {}).get('required_last_commits_match', 10)

    history_stats = GitUtils.get_commit_history_stats(abs_path, last_n=required_n)
    identity = _resolve_identity(abs_path, history_stats)
    
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
            'url': remote_url,
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
        "classification": classification,
        "status": status_msg,
        "guidance": guidance,
        "is_git": True,
        "backup_needed": backup_needed
    }

    return RepoStatus(
        path=abs_path,
        local=local,
        remote=remote,
        summary=summary,
        identity=identity
    )

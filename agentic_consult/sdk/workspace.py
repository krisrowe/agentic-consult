import json
import os
from pathlib import Path
from dataclasses import asdict
from typing import List, Dict, Any

from agentic_consult.backup.status import assess_repo_status
from agentic_consult.backup.git_utils import GitUtils

def find_workspace_root(start_path: Path) -> Path:
    """Finds the root of the workspace (git repo root or current dir)."""
    current = start_path.resolve()
    for parent in [current] + list(current.parents):
        if (parent / ".git").is_dir():
            return parent
    return current

def resolve_workspace_paths(explicit_paths=None) -> list[Path]:
    """
    Resolves workspace paths from:
    1. Explicit arguments
    2. .gemini/settings.json (workspace.folders)
    3. .claude/settings.json (workspace.folders)
    4. Current git root or CWD
    """
    if explicit_paths:
        return [Path(p).resolve() for p in explicit_paths]

    cwd = Path.cwd()
    root = find_workspace_root(cwd)
    
    found_paths = set()
    
    # Check .gemini/settings.json
    gemini_settings = root / ".gemini" / "settings.json"
    if gemini_settings.exists():
        try:
            with open(gemini_settings) as f:
                data = json.load(f)
                # Check workspace.folders
                folders = data.get("workspace", {}).get("folders", [])
                for folder in folders:
                    if isinstance(folder, str):
                        found_paths.add(Path(folder).expanduser().resolve())
                    elif isinstance(folder, dict) and "path" in folder:
                        found_paths.add(Path(folder["path"]).expanduser().resolve())
                
                # Check context.includeDirectories
                include_dirs = data.get("context", {}).get("includeDirectories", [])
                for folder in include_dirs:
                    if isinstance(folder, str):
                        # Handle relative paths from the settings file location
                        p = Path(folder).expanduser()
                        if not p.is_absolute():
                            p = (root / p).resolve()
                        found_paths.add(p)
        except Exception:
            pass

    # Check .claude/settings.json
    claude_settings = root / ".claude" / "settings.json"
    if claude_settings.exists():
        try:
             with open(claude_settings) as f:
                data = json.load(f)
                # Check workspace.folders
                folders = data.get("workspace", {}).get("folders", [])
                for folder in folders:
                    if isinstance(folder, str):
                        found_paths.add(Path(folder).expanduser().resolve())
                    elif isinstance(folder, dict) and "path" in folder:
                        found_paths.add(Path(folder["path"]).expanduser().resolve())

                # Check context.includeDirectories
                include_dirs = data.get("context", {}).get("includeDirectories", [])
                for folder in include_dirs:
                    if isinstance(folder, str):
                        # Handle relative paths from the settings file location
                        p = Path(folder).expanduser()
                        if not p.is_absolute():
                            p = (root / p).resolve()
                        found_paths.add(p)
        except Exception:
            pass
            
    # Always include the detected root (CWD or git root)
    found_paths.add(root)

    if found_paths:
        return sorted(list(found_paths))
        
    return [root]

def get_workspace_status(paths: list[str] = None, scan: bool = True) -> List[Dict[str, Any]]:
    """
    Analyzes workspace status, identity, and git state.

    Identifies git repositories within the resolved workspace paths.
    Always includes the current workspace root (git repo or CWD) in the check.
    If 'scan' is True, also checks immediate subdirectories of any non-repo path.
    
    Args:
        paths: List of explicit paths to check. If None, resolves from settings.
        scan: Whether to scan subdirectories for git repos.
        
    Returns:
        List of dictionaries containing repository status details. Each dict includes:
        - path: Absolute path to the repository.
        - summary: Dict with high-level status:
            - classification: 'Public Remote' (GitHub Public), 'Private Remote' (GitHub Private), 'Other Remote' (Non-GitHub), 'Local Only'.
            - status: 'Clean', 'Dirty' (uncommitted), 'Ahead' (unpushed), 'Behind' (unpulled), 'Sync Error'.
            - guidance: Actionable advice (e.g., "Push to remote").
        - identity: Dict with 'email', 'confidence', 'source'.
        - local: Dict with 'status' and 'stats' (staged, unstaged, untracked).
        - remote: Dict with 'status' and 'stats' (unpushed, unpulled).
    """
    resolved_paths = resolve_workspace_paths(paths)
    repos_to_check = []
    
    for p in resolved_paths:
        if GitUtils.is_git_repo(str(p)):
            repos_to_check.append(p)
        elif scan and p.is_dir():
             # Scan immediate subdirs
             try:
                 for item in p.iterdir():
                     if item.is_dir() and GitUtils.is_git_repo(str(item)):
                         repos_to_check.append(item)
             except PermissionError:
                 pass
    
    # De-duplicate and sort
    repos_to_check = sorted(list(set(repos_to_check)))
    
    results = [assess_repo_status(str(p)) for p in repos_to_check]
    return [asdict(r) for r in results]

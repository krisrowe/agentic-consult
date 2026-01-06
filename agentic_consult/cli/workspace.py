import click
import json
import os
import sys
from pathlib import Path
from dataclasses import asdict
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
            
    if found_paths:
        return sorted(list(found_paths))
        
    return [root]

@click.command(name="workspace")
@click.argument("paths", nargs=-1, type=click.Path(exists=True))
@click.option("--format", type=click.Choice(["text", "json"]), default="text", help="Output format.")
@click.option("--scan/--no-scan", default=True, help="Scan subdirectories if path is not a git repo.")
def workspace(paths, format, scan):
    """
    Analyzes workspace status, identity, and git state.
    
    If paths are provided, checks those specific directories.
    If no paths are provided, attempts to resolve workspace folders from:
    1. .gemini/settings.json
    2. .claude/settings.json
    3. Current git repository root or CWD
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

    if format == "json":
        data = [asdict(r) for r in results]
        click.echo(json.dumps(data, indent=2))
    else:
        if not results:
            click.echo("No git repositories found in workspace.")
            if resolved_paths:
                click.echo("\nChecked locations:")
                for p in resolved_paths:
                    click.echo(f"  - {p}")
            return

        headers = ["Path", "Class", "Status", "Identity", "Confidence"]
        rows = []
        
        for r in results:
            s = r.summary
            i = r.identity
            
            path_display = r.path
            home = os.path.expanduser("~")
            if path_display.startswith(home):
                path_display = "~" + path_display[len(home):]
            
            classification = s.get('classification', 'Unknown')
            status_str = s['status']
            identity_email = i.get('email') or "?"
            confidence = i.get('confidence', 'None')
            
            rows.append([path_display, classification, status_str, identity_email, confidence])

        # Calculate column widths
        col_widths = [len(h) for h in headers]
        for row in rows:
            for idx, item in enumerate(row):
                col_widths[idx] = max(col_widths[idx], len(str(item)))
        
        # Add padding
        col_widths = [w + 2 for w in col_widths]
        
        # Print Table
        header_row = "".join(h.ljust(w) for h, w in zip(headers, col_widths))
        click.echo(header_row)
        click.echo("-" * len(header_row))
        
        for row in rows:
            click.echo("".join(str(item).ljust(w) for item, w in zip(row, col_widths)))
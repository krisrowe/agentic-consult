import click
import json
import os
import sys
from pathlib import Path
from rich.console import Console
from rich.table import Table
from agentic_consult.sdk.workspace import get_workspace_status, find_workspace_root

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
    
    Output distinguishes the current repository (👉) from other workspace
    repositories.
    """
    results = get_workspace_status(paths=list(paths) if paths else None, scan=scan)

    if format == "json":
        click.echo(json.dumps(results, indent=2))
        return

    if not results:
        click.echo("No git repositories found in workspace.")
        return

    # Identify current root
    current_root = find_workspace_root(Path.cwd())
    
    current_repo = None
    workspace_repos = []
    
    for r in results:
        # Normalize paths for comparison
        if Path(r['path']).resolve() == current_root.resolve():
            current_repo = r
        else:
            workspace_repos.append(r)

    # Sort others alphabetically
    workspace_repos.sort(key=lambda x: x['path'])
    
    # Combined list: Current first, then others
    all_repos = []
    if current_repo:
        current_repo['_is_current'] = True
        all_repos.append(current_repo)
    
    for r in workspace_repos:
        r['_is_current'] = False
        all_repos.append(r)

    console = Console()
    table = Table(box=None, padding=(0, 2))
    
    # Columns
    table.add_column("Path", style="cyan", no_wrap=True)
    table.add_column("Class", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Stats", style="yellow")
    table.add_column("Git Identity", style="blue")
    table.add_column("Identity Clear")

    for r in all_repos:
        s = r['summary']
        i = r['identity']
        
        path_display = r['path']
        home = os.path.expanduser("~")
        if path_display.startswith(home):
            path_display = "~" + path_display[len(home):]
        
        # Add icon/indent
        is_current = r.get('_is_current', False)
        prefix = "👉 " if is_current else "   "
        path_display = prefix + path_display
        
        # Row styling for current repo
        row_style = "bold" if is_current else None

        classification = s.get('classification', 'Unknown')
        status_str = s['status']
        identity_email = i.get('email') or "?"
        confidence = i.get('confidence', 'None')
        
        # Format Stats
        local_stats = r.get('local', {}).get('stats', {})
        remote_stats = r.get('remote', {}).get('stats', {})
        
        staged = local_stats.get('staged', 0)
        unstaged = local_stats.get('unstaged', 0)
        untracked = local_stats.get('untracked', 0)
        unpushed = remote_stats.get('unpushed', 0)
        
        stats_parts = []
        if staged: stats_parts.append(f"S:{staged}")
        if unstaged: stats_parts.append(f"M:{unstaged}")
        if untracked: stats_parts.append(f"U:{untracked}")
        if unpushed: stats_parts.append(f"↑{unpushed}")
        
        stats_str = " ".join(stats_parts) if stats_parts else "-"
        
        table.add_row(
            path_display, 
            classification, 
            status_str, 
            stats_str, 
            identity_email, 
            confidence, 
            style=row_style
        )
    
    console.print(table)
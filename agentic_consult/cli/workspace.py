import click
import json
import os
import sys
from agentic_consult.sdk.workspace import get_workspace_status

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
    results = get_workspace_status(paths=list(paths) if paths else None, scan=scan)

    if format == "json":
        click.echo(json.dumps(results, indent=2))
    else:
        if not results:
            click.echo("No git repositories found in workspace.")
            return

        headers = ["Path", "Class", "Status", "Identity", "Confidence"]
        rows = []
        
        for r in results:
            # r is a dict now
            s = r['summary']
            i = r['identity']
            
            path_display = r['path']
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
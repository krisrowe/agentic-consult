import click
import json
import os
from dataclasses import asdict
from agentic_consult.backup.status import assess_repo_status

@click.command(name="repo-status")
@click.argument("path", default=".", type=click.Path(exists=True))
@click.option("--format", type=click.Choice(["text", "json"]), default="text", help="Output format.")
def repo_status(path, format):
    """
    Checks the status of a git repository (Local-Only or Remote) and provides backup guidance.
    """
    status = assess_repo_status(path)
    
    if format == "json":
        click.echo(json.dumps(asdict(status), indent=2))
    else:
        s = status.summary
        click.echo(f"\nRepository: {s['name']} ({status.path})")
        click.echo(f"Type:       {s['type']}")
        
        status_color = "green" if not s['backup_needed'] and s['is_git'] else "yellow" if s['backup_needed'] else "red"
        click.secho(f"Status:     {s['status']}", fg=status_color)
        
        click.echo(f"Guidance:   {s['guidance']}")
        
        # Local Details
        local = status.local
        if local['status'] == "DIRTY":
            stats = local['stats']
            click.echo(f"Local:      Dirty (Staged: {stats.get('staged', 0)}, Unstaged: {stats.get('unstaged', 0)}, Untracked: {stats.get('untracked', 0)})")
        else:
            click.echo(f"Local:      {local['status']}")

        # Remote Details
        remote = status.remote
        if s['type'] == "Remote":
            if remote['status'] in ["AHEAD", "BEHIND", "DIVERGED"]:
                stats = remote['stats']
                click.echo(f"Remote:     {remote['status']} (Unpushed: {stats.get('unpushed', 0)}, Unpulled: {stats.get('unpulled', 0)})")
            else:
                 click.echo(f"Remote:     {remote['status']}")
        elif s['type'] == "Local-Only":
             if remote['status'] == "SYNCED":
                 click.echo(f"Backup:     SYNCED (Hash: {remote['stats'].get('local_hash')[:7]}...)")
             else:
                 click.echo(f"Backup:     {remote['status']}")


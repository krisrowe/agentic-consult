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
        click.echo(f"\nRepository: {status.name} ({status.path})")
        click.echo(f"Type:       {status.type}")
        
        status_color = "green" if not status.backup_needed and status.is_git else "yellow" if status.backup_needed else "red"
        click.secho(f"Status:     {status.status}", fg=status_color)
        
        click.echo(f"Guidance:   {status.guidance}")
        
        if status.details.get('dirty_stats'):
            stats = status.details['dirty_stats']
            if any(stats.values()):
                click.echo(f"Dirty:      Staged: {stats['staged']}, Unstaged: {stats['unstaged']}, Untracked: {stats['untracked']}")
                
        if status.type == "Remote" and status.details.get('remote_status'):
             click.echo(f"Remote:     {status.details['remote_status']}")


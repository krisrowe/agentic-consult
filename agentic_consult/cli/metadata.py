import click
import sys
from agentic_consult.backup.metadata_manager import BackupMetadataManager

@click.group()
def metadata():
    """Manage backup metadata stored in git config."""
    pass

@metadata.command()
@click.argument('path', default='.', type=click.Path(exists=True))
def show(path):
    """View the current backup metadata for the repository."""
    try:
        manager = BackupMetadataManager(path)
        desc, keywords = manager.get_metadata()
        
        click.echo(f"Repository: {manager.repo_path}")
        click.echo(f"Description: {desc or '(none)'}")
        click.echo(f"Keywords: {keywords or '(none)'}")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

@metadata.command()
@click.argument('path', default='.', type=click.Path(exists=True))
@click.option('--desc', help="Description for the backup.")
@click.option('--keywords', help="Keywords for the backup (space-separated).")
def set(path, desc, keywords):
    """Manually set backup metadata in git config."""
    try:
        manager = BackupMetadataManager(path)
        if desc or keywords:
            manager.set_metadata(desc, keywords)
            click.echo("Metadata updated.")
        else:
            click.echo("No changes specified.")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

@metadata.command()
@click.argument('path', default='.', type=click.Path(exists=True))
def clear(path):
    """Clear backup metadata from git config."""
    try:
        manager = BackupMetadataManager(path)
        manager.clear_metadata()
        click.echo("Metadata cleared.")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

@metadata.command()
@click.argument('path', default='.', type=click.Path(exists=True))
@click.option('--dry-run', is_flag=True, help="Show the proposal without saving.")
@click.option('--yes', '-y', is_flag=True, help="Skip confirmation prompt.")
def generate(path, dry_run, yes):
    """Generate backup metadata using Gemini."""
    try:
        manager = BackupMetadataManager(path)
        new_desc, new_keywords = manager.generate_proposal()

        click.echo("\nProposed Metadata:")
        click.echo(f"Description: {new_desc}")
        click.echo(f"Keywords: {new_keywords}\n")

        if dry_run:
            return

        if yes or click.confirm("Save to git config?"):
            manager.set_metadata(new_desc, new_keywords)
            click.echo("Metadata saved.")
        else:
            click.echo("Cancelled.")
            
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
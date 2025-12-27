import click
import sys
import json
from dataclasses import asdict
from agentic_consult.backup.config_manager import BackupConfigManager
from agentic_consult.backup.orchestrator import BackupOrchestrator
from agentic_consult.backup.exceptions import BackupError
from agentic_consult.backup.results import BackupStatus

@click.group()
def backup():
    """Backup management commands."""
    pass

@backup.command()
@click.option('--folder-name', help="Name of the Google Drive folder to use.")
@click.option('--folder-id', help="ID of an existing Google Drive folder.")
@click.option('--create', is_flag=True, help="Create the folder if it doesn't exist (used with --folder-name).")
def config(folder_name, folder_id, create):
    """Configures the Google Drive folder for backups."""
    manager = BackupConfigManager()
    try:
        final_id = manager.configure_drive_folder(folder_name, folder_id, create)
        click.echo(f"Configuration saved. Backups will use folder ID: {final_id}")
    except (ValueError, BackupError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

@backup.command()
@click.option('--force', is_flag=True, help="Force backup even if repositories are dirty (Non-interactive mode).")
@click.option('--skip-dirty', is_flag=True, help="Skip dirty repositories instead of failing (Non-interactive mode).")
@click.option('--non-interactive', is_flag=True, help="Disable interactive prompts.")
@click.option('--format', type=click.Choice(['text', 'json']), default='text', help="Output format for the summary.")
def run(force, skip_dirty, non_interactive, format):
    """Runs the backup process."""
    is_interactive = sys.stdin.isatty() and not non_interactive
    
    orchestrator = BackupOrchestrator()
    try:
        results = orchestrator.run_backups(force=force, skip_dirty=skip_dirty, interactive=is_interactive)
        
        if format == 'json':
            # Serialize to JSON
            output_data = []
            for provider_res in results:
                # Convert dataclass to dict
                p_dict = asdict(provider_res)
                # Convert Enums to string in items
                p_dict['items'] = [
                    {k: (v.value if isinstance(v, BackupStatus) else v) for k, v in asdict(item).items()}
                    for item in provider_res.items
                ]
                output_data.append(p_dict)
            click.echo(json.dumps(output_data, indent=2))
            
        else:
            # Print ASCII Table to stdout
            click.echo("\n" + "="*80)
            click.echo(f"{ 'ITEM':<30} | {'STATUS':<10} | {'DETAILS'}")
            click.echo("-" * 80)
            
            for provider_res in results:
                for item in provider_res.items:
                    status_icon = "✅" if item.status == BackupStatus.SUCCESS \
                                  else "❌" if item.status == BackupStatus.FAILED \
                                  else "⚠️ " if item.status == BackupStatus.DIRTY \
                                  else "⏩" # NO_CHANGE, NOT_FOUND, USER_SKIPPED

                    status_text = f"{status_icon} {item.status.value}"
                    
                    # Truncate message if too long
                    msg = item.message.replace('\n', ' ')
                    if len(msg) > 35:
                        msg = msg[:32] + "..."
                        
                    click.echo(f"{item.name:<30} | {status_text:<10} | {msg}")
            
            click.echo("="*80 + "\n")

    except (ValueError, BackupError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
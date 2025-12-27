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
@click.option('--create', is_flag=True, help="Create the folder if it doesn't exist.")
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
@click.option('--force', is_flag=True, help="Force backup of dirty repositories (non-interactive).")
@click.option('--skip-dirty', is_flag=True, help="Skip dirty repositories (non-interactive).")
@click.option('--non-interactive', is_flag=True, help="Disable interactive prompts.")
@click.option('--format', type=click.Choice(['text', 'json']), default='text', help="Output format.")
def run(force, skip_dirty, non_interactive, format):
    """Runs the backup process."""
    is_interactive = sys.stdin.isatty() and not non_interactive
    
    orchestrator = BackupOrchestrator()
    try:
        results = orchestrator.run_backups(force=force, skip_dirty=skip_dirty, interactive=is_interactive)
        
        # Combine all items and group by type for printing
        all_items = []
        for res in results:
            all_items.extend(res.items)
            
        # Group by type (Home, Repo, etc.)
        grouped_items = {}
        for item in all_items:
            if item.type not in grouped_items:
                grouped_items[item.type] = []
            grouped_items[item.type].append(item)

        if format == 'json':
            # Create a serializable version of the grouped items
            json_output = {
                group: [asdict(item) for item in items]
                for group, items in grouped_items.items()
            }
            # Convert enums to strings for JSON
            for group, items in json_output.items():
                for item in items:
                    item['status'] = item['status'].value
            click.echo(json.dumps(json_output, indent=2))
            
        else:
            # Print ASCII Table
            ITEM_WIDTH = 38
            TYPE_WIDTH = 8
            STATUS_WIDTH = 12
            
            click.echo("\n" + "="*80)
            click.echo(f"{'ITEM':<{ITEM_WIDTH}} | {'TYPE':<{TYPE_WIDTH}} | {'STATUS':<{STATUS_WIDTH}} | {'DETAILS'}")
            click.echo("-" * 80)
            
            for group_name in sorted(grouped_items.keys()):
                for item in grouped_items[group_name]:
                    status_icon = "✅" if item.status == BackupStatus.SUCCESS else \
                                  "❌" if item.status == BackupStatus.FAILED else \
                                  "⚠️ " if item.status == BackupStatus.DIRTY else \
                                  "ℹ️ " # NO_CHANGE or NOT_FOUND
                    
                    status_text = item.status.value
                    
                    # Pad status text *before* adding icon for alignment
                    padded_status = f"{status_text:<{STATUS_WIDTH - 2}}" # -2 for icon and space
                    full_status = f"{status_icon} {padded_status}"
                    
                    item_name = item.name
                    if len(item_name) > ITEM_WIDTH:
                        item_name = item_name[:ITEM_WIDTH-3] + "..."
                        
                    type_icon = "🏠" if item.type == "Home" else "🗂️" if item.type == "Repo" else ""
                    type_text = f"{type_icon} {item.type}"
                    
                    msg = item.message.replace('\n', ' ')
                    if len(msg) > 25:
                        msg = msg[:22] + "..."
                        
                    click.echo(f"{item_name:<{ITEM_WIDTH}} | {type_text:<{TYPE_WIDTH}} | {full_status} | {msg}")
            
            click.echo("="*80 + "\n")

    except (ValueError, BackupError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
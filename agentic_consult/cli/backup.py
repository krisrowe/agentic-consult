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

@backup.command(name="all")
@click.option('--force', is_flag=True, help="Force backup of dirty repositories (non-interactive).")
@click.option('--skip-dirty', is_flag=True, help="Skip dirty repositories (non-interactive).")
@click.option('--non-interactive', is_flag=True, help="Disable interactive prompts.")
@click.option('--dry-run', is_flag=True, help="Simulate backup without uploading.")
@click.option('--format', type=click.Choice(['text', 'json']), default='text', help="Output format.")
def run_all(force, skip_dirty, non_interactive, dry_run, format):
    """Runs the backup process for all configured providers."""
    is_interactive = sys.stdin.isatty() and not non_interactive
    
    orchestrator = BackupOrchestrator()
    try:
        results = orchestrator.run_backups(force=force, skip_dirty=skip_dirty, interactive=is_interactive, dry_run=dry_run)
        
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
            # Create a serializable version of the ProviderResults
            json_output = []
            for res in results:
                res_dict = {
                    'provider_name': res.provider_name,
                    'status': res.status,
                    'message': res.message,
                    'items': [asdict(item) for item in res.items]
                }
                # Convert enums to strings
                for item in res_dict['items']:
                    item['status'] = item['status'].value
                json_output.append(res_dict)
            click.echo(json.dumps(json_output, indent=2))
            
        else:
            # Print ASCII Table
            ITEM_WIDTH = 38
            TYPE_WIDTH = 14  # Expanded for "Remote Repo"
            STATUS_WIDTH = 12
            
            click.echo("\n" + "="*98)
            click.echo(f"{ 'ITEM':<{ITEM_WIDTH}} | { 'TYPE':<{TYPE_WIDTH}} | { 'STATUS':<{STATUS_WIDTH}} | {'DETAILS'}")
            click.echo("-" * 98)
            
            for group_name in sorted(grouped_items.keys()):
                for item in grouped_items[group_name]:
                    status_icon = "✅" if item.status == BackupStatus.SUCCESS else \
                                  "❌" if item.status == BackupStatus.FAILED else \
                                  "⚠️ " if item.status == BackupStatus.DIRTY else \
                                  "⏳" if item.status == BackupStatus.PENDING else \
                                  "ℹ️ " # NO_CHANGE or NOT_FOUND
                    
                    status_text = item.status.value
                    
                    # Pad status text *before* adding icon for alignment
                    padded_status = f"{status_text:<{STATUS_WIDTH - 2}}" # -2 for icon and space
                    full_status = f"{status_icon} {padded_status}"
                    
                    item_name = item.name
                    if len(item_name) > ITEM_WIDTH:
                        item_name = item_name[:ITEM_WIDTH-3] + "..."
                        
                    type_icon = "🏠" if item.type == "Home" else "📂" if "Repo" in item.type else ""
                    # Pad the type name first, then add icon
                    padded_type = f"{item.type:<{TYPE_WIDTH - 2}}"
                    type_text = f"{type_icon} {padded_type}"
                    
                    msg = item.message.replace('\n', ' ')
                    if len(msg) > 30:
                        msg = msg[:27] + "..."
                        
                    click.echo(f"{item_name:<{ITEM_WIDTH}} | {type_text} | {full_status} | {msg}")
            
            click.echo("="*98 + "\n")

    except (ValueError, BackupError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

@backup.command(name='local-repo')
@click.argument('path', default='.', type=click.Path(exists=True))
@click.option('--force', is_flag=True, help="Force backup even if repository is dirty.")
@click.option('--skip-dirty', is_flag=True, help="Skip if dirty instead of prompting/failing.")
@click.option('--non-interactive', is_flag=True, help="Disable interactive prompts.")
def local_repo(path, force, skip_dirty, non_interactive):
    """Backs up a single git repository, regardless of whether it has remotes."""
    import os
    from agentic_consult.backup.providers.local_repos import LocalRepoBackup
    from agentic_consult.backup.folder_providers.factory import get_folder_provider
    from agentic_consult.config import get_backups_google_drive_folder_id
    import tempfile
    import shutil

    repo_path = os.path.abspath(path)
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        click.echo(f"Error: Not a git repository: {repo_path}", err=True)
        sys.exit(1)

    try:
        # Initial Setup (similar to orchestrator)
        folder_id = get_backups_google_drive_folder_id()
        if not folder_id:
            raise BackupError("Backup folder not configured. Run 'consult backup config' first.")

        folder_provider = get_folder_provider()
        provider_folder_id = folder_provider.ensure_folder_path(["local-only-repos"], root_id=folder_id)

        # Execute
        provider = LocalRepoBackup()
        options = {
            'force': force,
            'skip_dirty': skip_dirty,
            'interactive': sys.stdin.isatty() and not non_interactive
        }
        
        temp_dir = tempfile.mkdtemp(prefix="consult_single_backup_")
        try:
            result = provider.backup_single_repo(
                repo_path=repo_path,
                folder_provider=folder_provider,
                provider_folder_id=provider_folder_id,
                temp_dir=temp_dir,
                options=options
            )
            # Verbose output for single run
            click.echo(f"Backup of '{result.name}' repo: {result.status.value.upper()} ({result.message})")
            if result.status == BackupStatus.FAILED:
                sys.exit(1)

        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

    except (ValueError, BackupError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

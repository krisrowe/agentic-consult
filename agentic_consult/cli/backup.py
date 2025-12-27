import click
import subprocess
from pathlib import Path
import shutil

from agentic_consult.config import load_main_config, get_config_path
from agentic_consult.customers import get_active_customers_root
from agentic_consult.backup import perform_backup

@click.command()
@click.option('--output-dir', '-o', type=click.Path(path_type=Path), help="Local directory to save archives.")
@click.option('--no-upload', is_flag=True, help="Do not upload to Google Drive.")
def backup(output_dir, no_upload):
    """Backs up config and customer data."""
    config = load_main_config()
    config_path = get_config_path()
    
    if config_path and config_path.exists():
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(config_path, output_dir / config_path.name)
            click.echo(f"Saved {config_path.name} to {output_dir}")
        parent_id = config.get('google_drive_all_customers_folder_id')
        if parent_id and not no_upload:
            click.echo(f"Uploading config to {parent_id}...")
            try:
                subprocess.run(['gwsa', 'drive', 'upload', '--parent', parent_id, '--file', str(config_path)], check=True)
            except Exception as e:
                click.echo(f"Main config upload failed: {e}", err=True)

    customers_root = get_active_customers_root()
    perform_backup(config, customers_root, output_dir, no_upload)

import shutil
import datetime
import subprocess
import os
import click
from pathlib import Path
from agentic_consult.customers import _parse_customer_yaml

def perform_backup(config, customers_root, output_dir=None, no_upload=False):
    # 1. Backup Main Config
    parent_id = config.get('google_drive_all_customers_folder_id')
    # logic to backup config file if we can find it? 
    # The CLI passes config dict, but we need the file path.
    # We'll assume the caller handled config.yaml backup or we need to pass the path.
    
    # 2. Iterate Customers
    if not customers_root.exists():
        click.echo("No customers directory found.", err=True)
        return

    click.echo(f"Scanning customers in {customers_root}...")
    for d in customers_root.iterdir():
        if d.is_dir():
            c_yaml = d / "customer.yaml"
            if c_yaml.exists():
                cust = _parse_customer_yaml(c_yaml)
                name = cust.get('name', d.name)
                drive_id = cust.get('drive_folder_id')
                
                click.echo(f"Processing customer: {name}...")
                timestamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
                zip_name = f"{cust.get('slug', d.name)}-backup-{timestamp}"
                
                # Create Zip in /tmp
                zip_path_str = shutil.make_archive(str(Path('/tmp') / zip_name), 'zip', root_dir=d.parent, base_dir=d.name)
                zip_path = Path(zip_path_str)
                
                if output_dir:
                    output_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy(zip_path, output_dir / zip_path.name)
                    click.echo(f"Saved archive to {output_dir / zip_path.name}")

                if not no_upload and drive_id:
                    click.echo(f"Uploading to Drive folder {drive_id}...")
                    try:
                        subprocess.run(['gwsa', 'drive', 'upload', '--parent', drive_id, '--file', str(zip_path)], check=True)
                        click.echo("Upload success.")
                    except subprocess.CalledProcessError:
                        click.echo("Upload failed.")
                
                os.remove(zip_path)

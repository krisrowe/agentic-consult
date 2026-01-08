import os
import sys
import hashlib
import click
import logging
import io
from pathlib import Path
from googleapiclient.http import MediaIoBaseDownload
from agentic_consult.config import load_main_config
from agentic_consult.backup.drive import DriveClient

logger = logging.getLogger(__name__)

# Constants
BACKUP_FOLDER_KEY = "google_drive_folder_id"

def get_backup_folder_id():
    config = load_main_config()
    backups = config.get('backups', {})
    return backups.get(BACKUP_FOLDER_KEY)

def get_user_home_paths():
    config = load_main_config()
    user_home = config.get('backups', {}).get('user_home', {})
    if not user_home.get('enabled'):
        return []
    return user_home.get('paths', [])

def get_local_md5(path):
    if not os.path.exists(path): return None
    hash_md5 = hashlib.md5()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except (IOError, OSError):
        return None

def download_file(service, file_id, local_path):
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
    
    # Ensure parent dir exists
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    
    with open(local_path, 'wb') as f:
        f.write(fh.getbuffer())

def restore_item(drive_client, drive_file, relative_path, local_root, on_conflict):
    local_path = os.path.join(local_root, relative_path)
    is_folder = drive_file['mimeType'] == 'application/vnd.google-apps.folder'

    if is_folder:
        # Recurse
        q = f"'{drive_file['id']}' in parents and trashed = false"
        results = drive_client.service.files().list(q=q, fields="files(id, name, mimeType, md5Checksum)").execute()
        children = results.get('files', [])
        
        for child in children:
            restore_item(drive_client, child, os.path.join(relative_path, child['name']), local_root, on_conflict)
    else:
        # File logic
        local_md5 = get_local_md5(local_path)
        remote_md5 = drive_file.get('md5Checksum')

        if local_md5 == remote_md5:
            click.secho(f"SKIP (Identical): {relative_path}", fg="blue")
            return

        if os.path.exists(local_path):
            if on_conflict == 'fail':
                click.secho(f"ERROR: Conflict detected at '{relative_path}' and --on-conflict=fail.", fg="red", err=True)
                sys.exit(1)
            elif on_conflict == 'skip':
                click.secho(f"SKIP (Conflict): {relative_path}", fg="yellow")
                return
            elif on_conflict == 'overwrite':
                pass # Proceed to restore
            else: # ask
                click.secho(f"CONFLICT: {relative_path}", fg="yellow")
                if not click.confirm(f"Overwrite local {relative_path}?"):
                    click.secho("Skipped.", fg="yellow")
                    return
        
        click.secho(f"RESTORING: {relative_path}", fg="green")
        download_file(drive_client.service, drive_file['id'], local_path)
        
        # Post-restore permissions for SSH
        if ".ssh" in local_path and not local_path.endswith(".pub") and os.path.isfile(local_path):
             try:
                os.chmod(local_path, 0o600)
             except OSError:
                 pass


@click.command()
@click.option('--on-conflict', type=click.Choice(['ask', 'overwrite', 'skip', 'fail']), default='ask', 
              help="Strategy for handling existing files with different content. "
                   "Using 'overwrite', 'skip', or 'fail' ensures non-interactive execution.")
def restore(on_conflict):
    """
    Restores user-home configuration from Google Drive backup.
    
    This command downloads files from the configured Google Drive backup folder
    to the current user's home directory.
    """
    backup_id = get_backup_folder_id()
    if not backup_id:
        click.secho("Error: No backup folder ID configured. Run 'consult backup config' first.", fg="red")
        sys.exit(1)
    
    drive_client = DriveClient()
    
    click.echo(f"Scanning backup folder ({backup_id})...")
    
    # List files in the root backup folder
    q = f"'{backup_id}' in parents and trashed = false"
    results = drive_client.service.files().list(q=q, fields="files(id, name, mimeType, md5Checksum)").execute()
    backup_files = results.get('files', [])
    
    home_dir = os.path.expanduser("~")
    
    if not backup_files:
        click.secho("Backup folder is empty.", fg="yellow")
        return

    for item in backup_files:
        restore_item(drive_client, item, item['name'], home_dir, on_conflict)
import sys
from typing import Optional, Dict, Any
from agentic_consult.config import load_main_config, save_main_config
from agentic_consult.backup.folder_providers.factory import get_folder_provider
from agentic_consult.backup.exceptions import FolderAccessError, FolderExistsError, FolderNotFoundError, InvalidFolderNameError

class BackupConfigManager:
    """
    Manages the configuration for the backup system, specifically
    the Google Drive folder target.
    """
    def __init__(self):
        self.provider = get_folder_provider()

    def configure_drive_folder(self, folder_name: Optional[str], folder_id: Optional[str], create: bool) -> str:
        """
        Configures the backup folder based on user input.
        Returns the configured folder ID or raises ValueError on error.
        """
        if not folder_name and not folder_id:
            raise ValueError("You must specify either folder_name or folder_id.")

        final_folder_id = None
        
        if folder_id:
            # Validate ID exists and is accessible
            file_meta = self.provider.find_file_by_id(folder_id)
            if not file_meta or file_meta.get('mimeType') != 'application/vnd.google-apps.folder':
                 # Using the strong exception type here would be good, but CLI catches generic exceptions or we rely on specific ones?
                 # The prompt asked for "test_backup_run_with_inaccessible_folder_id_error (sdk show throw a specific strongly-typed exception which cli catches)"
                 # So I should raise specific exceptions.
                 raise FolderAccessError(f"Folder ID '{folder_id}' not found or is not a folder.")
            final_folder_id = folder_id
            print(f"Verified access to folder ID: {folder_id} ({file_meta.get('name')})")

        elif folder_name:
            if "/" in folder_name:
                 raise InvalidFolderNameError("Folder name cannot contain path separators.")
            
            # Search in My Drive (root)
            existing_id = self.provider.find_folder(folder_name) 
            
            if existing_id:
                if create:
                     raise FolderExistsError(f"Folder '{folder_name}' already exists but --create was passed.")
                final_folder_id = existing_id
                print(f"Found existing folder '{folder_name}' (ID: {existing_id}).")
            else:
                if not create:
                     raise FolderNotFoundError(f"Folder '{folder_name}' not found. Use --create to create it.")
                
                print(f"Creating new folder '{folder_name}'...")
                final_folder_id = self.provider.create_folder(folder_name)
                print(f"Created folder '{folder_name}' (ID: {final_folder_id}).")

        # Save to config
        config_data = load_main_config()
        config_data['backups_google_drive_folder_id'] = final_folder_id
        save_main_config(config_data)
        
        return final_folder_id
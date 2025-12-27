import os
import google.auth
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from typing import Optional, List, Dict, Any

class DriveClient:
    """
    A wrapper around the Google Drive API to support finding, uploading,
    and updating files (preserving history).
    """
    SCOPES = ['https://www.googleapis.com/auth/drive']

    def __init__(self):
        self.creds, _ = google.auth.default(scopes=self.SCOPES)
        self.service = build('drive', 'v3', credentials=self.creds)

    def find_file(self, name: str, parent_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Finds a file by name and optional parent folder ID."""
        query = f"name = '{name}' and trashed = false"
        if parent_id:
            query += f" and '{parent_id}' in parents"
        
        try:
            results = self.service.files().list(
                q=query,
                spaces='drive',
                fields='nextPageToken, files(id, name, mimeType)',
                pageSize=1
            ).execute()
            files = results.get('files', [])
            if files:
                return files[0]
            return None
        except HttpError as error:
            print(f"An error occurred searching for file '{name}': {error}")
            return None

    def find_file_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves metadata for a specific file ID."""
        try:
            return self.service.files().get(
                fileId=file_id,
                fields='id, name, mimeType, createdTime, modifiedTime'
            ).execute()
        except HttpError:
            return None

    def find_folder(self, name: str, parent_id: Optional[str] = None) -> Optional[str]:
        """Finds a folder by name and optional parent ID. Returns the folder ID."""
        file = self.find_file(name, parent_id)
        if file and file['mimeType'] == 'application/vnd.google-apps.folder':
            return file['id']
        return None

    def create_folder(self, name: str, parent_id: Optional[str] = None) -> str:
        """Creates a folder and returns its ID."""
        file_metadata = {
            'name': name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        if parent_id:
            file_metadata['parents'] = [parent_id]
        
        try:
            file = self.service.files().create(body=file_metadata, fields='id').execute()
            return file.get('id')
        except HttpError as error:
            print(f"An error occurred creating folder '{name}': {error}")
            raise

    def ensure_folder_path(self, path_parts: List[str], root_id: Optional[str] = None) -> str:
        """
        Ensures a folder path exists, creating missing folders as needed.
        Returns the ID of the final folder.
        """
        current_parent_id = root_id
        for folder_name in path_parts:
            folder_id = self.find_folder(folder_name, current_parent_id)
            if not folder_id:
                folder_id = self.create_folder(folder_name, current_parent_id)
            current_parent_id = folder_id
        return current_parent_id

    def upload_file(self, local_path: str, parent_id: str, name: Optional[str] = None) -> str:
        """Uploads a new file. Returns the file ID."""
        file_name = name or os.path.basename(local_path)
        file_metadata = {
            'name': file_name,
            'parents': [parent_id]
        }
        media = MediaFileUpload(local_path, resumable=True)
        
        try:
            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            return file.get('id')
        except HttpError as error:
            print(f"An error occurred uploading file '{local_path}': {error}")
            raise

    def update_file(self, file_id: str, local_path: str) -> str:
        """Updates an existing file's content (preserving history). Returns the file ID."""
        # We don't change the name, just the content
        media = MediaFileUpload(local_path, resumable=True)
        
        try:
            file = self.service.files().update(
                fileId=file_id,
                media_body=media,
                fields='id'
            ).execute()
            return file.get('id')
        except HttpError as error:
            print(f"An error occurred updating file ID '{file_id}': {error}")
            raise

    def sync_file(self, local_path: str, parent_id: str, name: Optional[str] = None) -> str:
        """
        Convenience method: Updates the file if it exists in the parent,
        otherwise uploads it.
        """
        file_name = name or os.path.basename(local_path)
        existing_file = self.find_file(file_name, parent_id)
        
        if existing_file:
            print(f"Updating existing file: {file_name} (ID: {existing_file['id']})")
            return self.update_file(existing_file['id'], local_path)
        else:
            print(f"Uploading new file: {file_name}")
            return self.upload_file(local_path, parent_id, name)
import os
import sys
import google.auth
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from typing import Optional, List, Dict, Any
from agentic_consult.backup.folder_providers.base import BackupsFolderProvider
from agentic_consult.backup.exceptions import (
    FolderAccessError, FolderNotFoundError, FolderExistsError, MultipleFoldersFoundError
)

class GoogleDriveBackupsFolderProvider(BackupsFolderProvider):
    """
    Google Drive implementation of the BackupsFolderProvider.
    Uses google-api-python-client to interact with Drive API v3.
    """
    SCOPES = ['https://www.googleapis.com/auth/drive']

    def __init__(self):
        try:
            self.creds, _ = google.auth.default(scopes=self.SCOPES)
            self.service = build('drive', 'v3', credentials=self.creds)
        except Exception as e:
            print(f"Warning: Failed to initialize Google Drive client: {e}", file=sys.stderr)
            self.service = None

    def find_files(self, name: str, parent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.service: return []
        query = f"name = '{name}' and trashed = false"
        if parent_id:
            query += f" and '{parent_id}' in parents"
        
        try:
            results = self.service.files().list(
                q=query,
                spaces='drive',
                fields='nextPageToken, files(id, name, mimeType, appProperties)',
                pageSize=10
            ).execute()
            return results.get('files', [])
        except HttpError as error:
            print(f"Drive API Error (find_files): {error}", file=sys.stderr)
            return []

    def find_file(self, name: str, parent_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        files = self.find_files(name, parent_id)
        return files[0] if files else None

    def find_file_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        if not self.service: return None
        try:
            return self.service.files().get(
                fileId=file_id,
                fields='id, name, mimeType, createdTime, modifiedTime'
            ).execute()
        except HttpError:
            return None

    def find_folder(self, name: str, parent_id: Optional[str] = None) -> Optional[str]:
        files = self.find_files(name, parent_id)
        folders = [f for f in files if f['mimeType'] == 'application/vnd.google-apps.folder']
        if len(folders) > 1:
            raise MultipleFoldersFoundError(f"Ambiguity detected for '{name}'")
        return folders[0]['id'] if folders else None

    def create_folder(self, name: str, parent_id: Optional[str] = None) -> str:
        if not self.service: raise FolderAccessError("Drive client not initialized")
        file_metadata = {'name': name, 'mimeType': 'application/vnd.google-apps.folder'}
        if parent_id: file_metadata['parents'] = [parent_id]
        try:
            file = self.service.files().create(body=file_metadata, fields='id').execute()
            return file.get('id')
        except HttpError as error:
            raise FolderAccessError(f"Failed to create folder '{name}': {error}")

    def ensure_folder_path(self, path_parts: List[str], root_id: Optional[str] = None) -> str:
        current_parent_id = root_id
        for folder_name in path_parts:
            folder_id = self.find_folder(folder_name, current_parent_id)
            if not folder_id:
                folder_id = self.create_folder(folder_name, current_parent_id)
            current_parent_id = folder_id
        return current_parent_id

    def sync_file(self, local_path: str, parent_id: str, name: Optional[str] = None, app_properties: Optional[Dict[str, str]] = None) -> str:
        file_name = name or os.path.basename(local_path)
        existing_file = self.find_file(file_name, parent_id)
        
        if existing_file:
            print(f"Updating existing file: {file_name} (ID: {existing_file['id']})", file=sys.stderr)
            return self._update_file(existing_file['id'], local_path, app_properties)
        else:
            print(f"Uploading new file: {file_name}", file=sys.stderr)
            return self._upload_file(local_path, parent_id, name, app_properties)

    def _upload_file(self, local_path: str, parent_id: str, name: Optional[str], app_properties: Optional[Dict[str, str]]) -> str:
        if not self.service: raise FolderAccessError("Drive client not initialized")
        file_metadata = {'name': name or os.path.basename(local_path), 'parents': [parent_id]}
        if app_properties:
            file_metadata['appProperties'] = app_properties
            
        media = MediaFileUpload(local_path, resumable=True)
        try:
            file = self.service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            return file.get('id')
        except HttpError as error:
            raise FolderAccessError(f"Upload failed: {error}")

    def _update_file(self, file_id: str, local_path: str, app_properties: Optional[Dict[str, str]]) -> str:
        if not self.service: raise FolderAccessError("Drive client not initialized")
        file_metadata = {}
        if app_properties:
            file_metadata['appProperties'] = app_properties
            
        media = MediaFileUpload(local_path, resumable=True)
        try:
            file = self.service.files().update(fileId=file_id, body=file_metadata, media_body=media, fields='id').execute()
            return file.get('id')
        except HttpError as error:
            raise FolderAccessError(f"Update failed: {error}")
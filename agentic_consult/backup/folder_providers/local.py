import os
import shutil
import json
from typing import Optional, List, Dict, Any
from agentic_consult.backup.folder_providers.base import BackupsFolderProvider
from agentic_consult.backup.exceptions import (
    FolderAccessError, FolderNotFoundError, FolderExistsError, MultipleFoldersFoundError
)

class LocalBackupsFolderProvider(BackupsFolderProvider):
    def __init__(self, root_path: Optional[str] = None):
        self.root_path = root_path or os.environ.get("LOCAL_BACKUPS_FOLDER")
        if not self.root_path:
             raise FolderAccessError("LOCAL_BACKUPS_FOLDER not set")
        os.makedirs(self.root_path, exist_ok=True)

    def _resolve_path(self, path_or_id: Optional[str]) -> str:
        if not path_or_id: return self.root_path
        if path_or_id.startswith(self.root_path): return path_or_id
        return os.path.join(self.root_path, path_or_id)

    def _get_meta_path(self, file_path: str) -> str:
        return file_path + ".meta"

    def find_files(self, name: str, parent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        parent_dir = self._resolve_path(parent_id)
        target_path = os.path.join(parent_dir, name)
        
        if os.path.exists(target_path):
            meta_path = self._get_meta_path(target_path)
            app_properties = {}
            if os.path.exists(meta_path):
                with open(meta_path, 'r') as f:
                    app_properties = json.load(f)
            
            return [{
                "id": target_path,
                "name": name,
                "mimeType": "application/vnd.google-apps.folder" if os.path.isdir(target_path) else "application/octet-stream",
                "appProperties": app_properties,
                "md5Checksum": self._get_local_md5(target_path) if os.path.isfile(target_path) else None
            }]
        return []

    def find_file(self, name: str, parent_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        files = self.find_files(name, parent_id)
        return files[0] if files else None

    def find_file_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        if os.path.exists(file_id):
            meta_path = self._get_meta_path(file_id)
            app_properties = {}
            if os.path.exists(meta_path):
                with open(meta_path, 'r') as f:
                    app_properties = json.load(f)
            return {
                "id": file_id,
                "name": os.path.basename(file_id),
                "mimeType": "application/vnd.google-apps.folder" if os.path.isdir(file_id) else "application/octet-stream",
                "appProperties": app_properties,
                "md5Checksum": self._get_local_md5(file_id) if os.path.isfile(file_id) else None,
                "createdTime": os.path.getctime(file_id), # Emulate
                "modifiedTime": os.path.getmtime(file_id) # Emulate
            }
        return None

    def find_folder(self, name: str, parent_id: Optional[str] = None) -> Optional[str]:
        files = self.find_files(name, parent_id)
        folders = [f for f in files if f['mimeType'] == 'application/vnd.google-apps.folder']
        if len(folders) > 1: raise MultipleFoldersFoundError(f"Ambiguity for '{name}'")
        return folders[0]['id'] if folders else None

    def create_folder(self, name: str, parent_id: Optional[str] = None) -> str:
        parent_dir = self._resolve_path(parent_id)
        target_path = os.path.join(parent_dir, name)
        os.makedirs(target_path, exist_ok=True)
        return target_path

    def ensure_folder_path(self, path_parts: List[str], root_id: Optional[str] = None) -> str:
        current_path = self._resolve_path(root_id)
        for part in path_parts:
            current_path = os.path.join(current_path, part)
            os.makedirs(current_path, exist_ok=True)
        return current_path

    def sync_file(self, local_path: str, parent_id: str, name: Optional[str] = None, app_properties: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        parent_dir = self._resolve_path(parent_id)
        file_name = name or os.path.basename(local_path)
        target_path = os.path.join(parent_dir, file_name)
        shutil.copy2(local_path, target_path)
        
        if app_properties:
            meta_path = self._get_meta_path(target_path)
            with open(meta_path, 'w') as f:
                json.dump(app_properties, f)
                
        return {"id": target_path, "name": file_name}

    def _get_local_md5(self, file_path):
        import hashlib
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
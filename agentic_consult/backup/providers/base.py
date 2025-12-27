from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from agentic_consult.backup.results import ProviderResult

class BackupsFolderProvider(ABC):
    """
    Abstract interface for backup storage operations.
    """

    @abstractmethod
    def find_folder(self, name: str, parent_id: Optional[str] = None) -> Optional[str]:
        """Finds a folder by name. Returns ID."""
        pass

    @abstractmethod
    def create_folder(self, name: str, parent_id: Optional[str] = None) -> str:
        """Creates a folder. Returns ID."""
        pass
    
    @abstractmethod
    def ensure_folder_path(self, path_parts: List[str], root_id: Optional[str] = None) -> str:
        """Ensures a folder path exists. Returns final ID."""
        pass

    @abstractmethod
    def find_file(self, name: str, parent_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Finds a file. Returns metadata dict (must contain 'id' and 'appProperties')."""
        pass

    @abstractmethod
    def find_files(self, name: str, parent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Finds all files matching the name."""
        pass
    
    @abstractmethod
    def find_file_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Finds a file/folder by its ID."""
        pass

    @abstractmethod
    def sync_file(self, local_path: str, parent_id: str, name: Optional[str] = None, app_properties: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Uploads or updates a file with optional metadata properties.
        Returns a dict with metadata, including at least 'id' and 'name'.
        """
        pass

class BackupProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def run(self, config: Dict[str, Any], options: Dict[str, Any]) -> ProviderResult:
        """
        Executes the backup logic.
        """
        pass

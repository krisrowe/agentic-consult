from dataclasses import dataclass
from typing import List, Optional
from enum import Enum

class BackupStatus(Enum):
    SUCCESS = "Success"
    FAILED = "Failed"
    NO_CHANGE = "No Change"
    DIRTY = "Dirty"
    NOT_FOUND = "Not Found"

@dataclass
class BackupItemResult:
    name: str
    status: BackupStatus
    message: str
    type: str  # e.g., "Repo", "Home"

@dataclass
class ProviderResult:
    provider_name: str
    status: str
    message: str
    items: List[BackupItemResult]

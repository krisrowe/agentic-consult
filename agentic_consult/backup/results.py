from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum

class BackupStatus(Enum):
    SUCCESS = "Success"
    FAILED = "Failed"
    NO_CHANGE = "No Change"
    DIRTY = "Dirty"
    NOT_FOUND = "Not Found"
    PENDING = "Pending"

@dataclass
class BackupItemResult:
    name: str
    status: BackupStatus
    message: str
    type: str  # e.g., "Repo", "Home"
    details: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ProviderResult:
    provider_name: str
    status: str
    message: str
    items: List[BackupItemResult]

from dataclasses import dataclass
from typing import List, Optional
from enum import Enum

class BackupStatus(Enum):
    SUCCESS = "Success"
    SKIPPED = "Skipped"
    FAILED = "Failed"

@dataclass
class BackupItemResult:
    name: str
    status: BackupStatus
    message: str

@dataclass
class ProviderResult:
    provider_name: str
    status: str # "success", "failure", "skipped" for the provider as a whole
    message: str
    items: List[BackupItemResult]

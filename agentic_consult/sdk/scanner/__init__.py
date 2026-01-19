"""SDK Scanner - pre-commit scanning for sensitive data.

Scans for user patterns, customer patterns, dollar amounts, identifiers,
OAuth tokens, local username, git identity, and runs external devws checks.
"""

from .core import run_scan, ScanReport, InvalidCheckModuleError, MissingUserConfigError
from .utils import CheckResult
from .steps import get_step_names

__all__ = [
    "run_scan",
    "ScanReport",
    "CheckResult",
    "InvalidCheckModuleError",
    "MissingUserConfigError",
    "get_step_names",
]

class BackupError(Exception):
    """Base class for backup-related exceptions."""
    pass

class BackupConfigurationError(BackupError):
    """Raised when configuration is missing or invalid."""
    pass

class FolderAccessError(BackupError):
    """Raised when the backup folder exists but is not accessible."""
    pass

class FolderNotFoundError(BackupError):
    """Raised when a specified folder cannot be found."""
    pass

class FolderExistsError(BackupError):
    """Raised when attempting to create a folder that already exists."""
    pass

class MultipleFoldersFoundError(BackupError):
    """Raised when multiple folders with the same name are found at the same location."""
    pass

class InvalidFolderNameError(BackupError):
    """Raised when a folder name is invalid."""
    pass
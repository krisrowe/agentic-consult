# Testing Philosophy for Backups SDK

This test suite is designed to verify the end-to-end business logic of the backup SDK without relying on network I/O, external services, or mocking frameworks.

## Core Principles

1.  **Isolate Business Logic:** The primary goal is to test our orchestration, configuration management, and provider logic, not the Google Drive API client itself.
2.  **No Network I/O:** Tests must run in network-isolated environments (like CI/CD runners) without requiring credentials or external service access.
3.  **No Mocking Frameworks:** We avoid libraries like `unittest.mock` and `patch`. 
    -   **Why?** Over-mocking leads to brittle tests that verify implementation details rather than behavior. It can mask integration bugs where components don't actually work together.
    -   **How?** We design our code to be testable. We use dependency injection, environment variables, and factory patterns to swap out heavy dependencies (like cloud storage) for lightweight, local implementations during testing.
    -   **Environment Overrides:** We explicitly allow the use of `monkeypatch.setenv` to redirect application behavior. This is not "mocking" in the traditional sense, but rather using the application's built-in configuration surface to set up an isolated test context.
    -   **Stop Rule:** If a test seems to require `patch` to work (e.g., to intercept a hard-coded function call), **STOP**. Do not patch it. Refactor the code or use provided override mechanisms (like environment variables) to enable testing.

## Testable Abstractions

### 1. Storage Backend (`BackupsFolderProvider`)
To abstract away Google Drive:
-   **`GoogleDriveBackupsFolderProvider`**: Production implementation using the Drive API.
-   **`LocalBackupsFolderProvider`**: Test implementation using the local filesystem.
-   **Switch:** The `get_folder_provider` factory checks the `LOCAL_BACKUPS_FOLDER` environment variable. If set, it returns the local provider rooted at that path.

### 2. Configuration Isolation
To avoid reading/writing the user's real `settings.json` or mocking the config loader:
-   **Switch:** The `get_config_path` function checks the `CONSULT_CONFIG_DIR` environment variable.
-   **Usage:** Tests use `monkeypatch.setenv("CONSULT_CONFIG_DIR", config_dir)` to point the application to a temporary directory. The application then reads/writes real configuration files in that isolated directory.

## How it Works

1.  **Test Setup:** 
    -   Create a temporary directory for backups and set `LOCAL_BACKUPS_FOLDER`.
    -   Create a temporary directory for config and set `CONSULT_CONFIG_DIR`.
2.  **Execution:** Run the SDK code. It writes "files" to the temp backup folder and saves "settings" to the temp config folder using real file I/O.
3.  **Verification:** Assert that the expected files exist in the temp backup folder and the expected JSON content is in the temp config folder.

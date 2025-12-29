# Testing Strategy

This project adheres to a **["Sociable Unit Testing"](https://martinfowler.com/bliki/UnitTest.html)** philosophy (also known as Component Testing). We prioritize tests that verify full features/transactions end-to-end without network I/O over isolated, granular unit tests that mock internal implementation details.

## Tier 1: Core Tests ("Sociable Unit Tests")
*   **Location**: `tests/unit/`
*   **Philosophy**: Test the full logic flow (e.g., CLI entry point -> Orchestrator -> Provider) but **MOCK** the absolute system boundaries (Network, external APIs like Google Drive/Gmail).
*   **Execution**: Fast, deterministic, run by default (`pytest`).
*   **Usage**: These are your primary tests. Add them whenever you add a feature. Use `unittest.mock` to simulate external dependencies (e.g., `agentic_consult.backup.folder_providers.factory.get_folder_provider`). Real file system operations (using temporary directories) are encouraged.

## Tier 2: External Tests ("Integration Tests")
*   **Location**: `tests/integration/` (or marked as `external`)
*   **Philosophy**: Test the contract with the outside world. These tests hit **REAL** external APIs (Google Drive, Gmail, TickTick).
*   **Execution**: Slow, flaky, require credentials. Excluded by default.
*   **Usage**: Write these sparingly to verify that our API client code actually works against the real provider.

## How to Run Tests

**Run Core Tests (Default):**
```bash
pytest
```

**Run External Tests (Requires Auth):**
```bash
pytest -m external
# or
pytest tests/integration/
```

## Adding New Tests
1.  **Refactoring?** Ensure `tests/unit/` still passes.
2.  **New Feature?** Add a "Sociable" test in `tests/unit/` that exercises the new command or workflow. Mock only the network calls.
3.  **New API Integration?** Add a small test in `tests/integration/` to verify the client works.

# Testing Strategy

This project adheres to a **["Sociable Unit Testing"](https://martinfowler.com/bliki/UnitTest.html)** philosophy (also known as Component Testing). We prioritize tests that verify full features or SDK transactions end-to-end without network I/O over isolated, granular "Solitary" unit tests that mock internal collaborators.

## Core Philosophy: Why Sociable?

We subscribe to the mantra: **"Functionality is an asset, code is a liability."** This extends to the test suite itself.

A test suite is code that demands maintenance and cognitive load. If we create a sprawling suite of "Solitary" tests (one for every internal function/class), we increase our liability without necessarily increasing our confidence in the system's behavior. Such suites become unwieldy, opaque, and eventually unmaintained because it becomes impossible to look at them and quickly assess "what functionality is covered?" versus "what implementation details are we testing?"

Instead, our "Core Tests" focus on **functional ROI**:
1.  **Test the Interface, Not the Internals**: We test from the public entry point (e.g., an SDK function or CLI command) down to the system boundary. This keeps the test suite readable as a specification of *capabilities*.
2.  **Use Real Collaborators**: If an SDK function calls a helper class, we let it use the *real* helper class. We only mock the final "edge" of the system (Network I/O, Third-Party APIs). This ensures refactoring internal helpers doesn't break tests unless the *outcome* changes.
3.  **Embrace the File System**: We do **not** shy away from real file system operations. We use isolated temporary directories (`tempfile` fixtures) for setup and teardown. This ensures our file handling logic is proven correct.
    *   *Exception*: If data is massive or practically impossible to generate/clean up in a test (e.g., huge binary assets), we may mock the file access layer, but this is rare.

## Tier 1: Core Tests ("Sociable Unit Tests")
*   **Location**: `tests/unit/`
*   **Execution**: Fast, deterministic, run by default (`pytest`).
*   **What to Mock**:
    *   Network calls (Google Drive, Gmail, TickTick API).
    *   System clocks/Time (if precision is required).
    *   Heavy external processes.
*   **What NOT to Mock**:
    *   Internal helper functions/classes.
    *   File system (read/write to temp dirs).
    *   Configuration parsers (write real config files to temp dirs).

## Tier 2: External Tests ("Integration Tests")
*   **Location**: `tests/integration/` (or marked as `external`)
*   **Philosophy**: Verify the contract with the outside world. These tests hit **REAL** external APIs.
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
2.  **New Feature?** Add a "Sociable" test in `tests/unit/` that exercises the new command/SDK function. Setup a temp directory, create necessary dummy files, invoke the code, and assert the output or file system state. Mock only the network.
3.  **Complex Isolated Logic?** Only if a specific algorithm is extremely complex and has many edge cases (e.g., a regex parser or math utility) do we write a Solitary test for it.
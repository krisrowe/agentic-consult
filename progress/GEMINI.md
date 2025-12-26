# Project Finalization & Verification Plan

This document outlines the final steps to verify all recent changes, including critical bug fixes, before publishing the repository.

---

### 1. Current State & Objective

- **SDK Migration**: The codebase has been migrated to the `google-genai` SDK (Commit `ca3d3c2`).
- **TickTick Integration Fixes**: Critical bug fixes for task fetching and creation have been implemented locally (Commit `c50b8d3`).
- **Objective**: The primary goal is to perform a definitive end-to-end test to verify the "Task Context Lifecycle". This ensures that tasks created as a result of one email are correctly fetched from the TickTick server and included as context for Gemini when processing the next email in a subsequent run.

---

### 2. Mandatory Verification: Sequential Replay Test

This test simulates a user processing emails chronologically over time.

#### **Step 0: Initial State Wipe**
- **Goal**: Ensure a completely clean slate for the test customer.
- **Command**:
  ```bash
  # Note: Customer-specific directory paths are used here for local testing.
  > ~/.config/agentic-consult/customers/[TEST_CUSTOMER]/emails_processed.txt && \
  rm -f ~/.config/agentic-consult/customers/[TEST_CUSTOMER]/tasks/tasks.json && \
  rm -rf ~/.config/agentic-consult/customers/[TEST_CUSTOMER]/issues/*
  ```

#### **Step 1: Process Email 1 (Chronologically Oldest)**
- **Goal**: Simulate the first event in a sequence.
- **Action**:
  1. Isolate the first email in the local cache (`emails.json`).
  2. Run `consult refresh [TEST_CUSTOMER] --no-dry-run --skip-fetch`.
- **Expected Outcome**:
  - A new task is created in the TickTick service based on the content of Email 1.
  - The `refresh` command completes. The local `tasks.json` may or may not be immediately updated, which is expected.

#### **Step 2: Process Email 2 (Chronologically Second)**
- **Goal**: Verify that the task created in Step 1 is used as context.
- **Action**:
  1. Isolate the second email in the local cache (`emails.json`).
  2. Run `consult refresh [TEST_CUSTOMER] --no-dry-run --skip-fetch`.
- **CRITICAL VERIFICATION**:
  - Before the Gemini call, the `refresh` command will fetch tasks from the TickTick server.
  - **Inspect the `gemini-input.txt` file.** It **must** contain the task created in Step 1 in its `<TASKS>` context block.
  - Observe the `deltas.json` to see how Gemini's decision was influenced by having the context of the existing task.

---

### 3. Final Pre-Push Verification Cycle

**Goal**: Ensure the repository is clean and all tests pass before committing.

**Commands**:
1.  `PYTHONPATH=. .venv/bin/pytest tests/unit tests/integration -v`
2.  `.venv/bin/consult precommit`
3.  `devws precommit`

---

### 4. Commit & Push to Private Repository

**Goal**: Commit the verified code and publish to a new private GitHub repository.

**Commands**:
1.  **Commit**:
    ```bash
    git add -A .
    git commit -m "feat: Implement and verify TickTick task context lifecycle"
    ```
2.  **Create Repository**: A new **private** repository named `agentic-consult` will be created.
3.  **Push**:
    ```bash
    git remote add origin <REPO_URL>
    git push -u origin main
    ```

---

### 5. Post-Push Cleanup

**Goal**: Remove any temporary or sensitive files created during this process.

**Command**:
```bash
rm -rf progress/
```
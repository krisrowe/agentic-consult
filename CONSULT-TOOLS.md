# Agentic Consult - Tool Guidance

This context file provides authoritative guidance on using the tools provided by the `agentic-consult` suite.

## Task Management (TickTick)

### Task Lifecycle & Archival Strategy
To maintain a clean active task list while preserving historical context, follow this lifecycle:

1.  **Completion:** When a task is verified as done, it should be removed from the active list (TickTick).
2.  **Archival:** Before deletion, the task's full detail must be preserved in the customer's local context.
3.  **Procedure:**
    *   **Resolve Path:** Use the `get_customer_info(slug)` tool to find the customer's local root path (`local.path`).
    *   **Target Directory:** Use `<local.path>/tasks/archive/`. Ensure this directory exists.
    *   **Execute:** Call `ticktick.delete_task` with:
        *   `task_id`: The ID of the completed task.
        *   `project_id`: The ID of the project.
        *   `otp`: Generated via `ticktick auth generate-otp`.
        *   `archive_path`: The fully resolved path to the customer's `tasks/archive/` folder.

**Why this matters:**
*   **Searchable History:** Future agents can find "what was done" by searching the local `tasks/archive` folder.
*   **Hygiene:** Keeps the active TickTick list focused on pending actions.

## Customer Issue Management



Technical issues and analysis tasks must follow a directory-based structure:



*   **Issue Folders:** Create a folder for each issue (`issues/<issue_slug>/`) containing a `README.md` and any attachments (e.g., `chat.md`, evidence).

*   **Resources:** Use `resources/` at the customer root for shared assets (full chat logs, diagrams, binaries) that span multiple issues.

*   **Active Issues:** Store folders directly in the `issues/` root (e.g., `issues/auth-failure/`).

*   **Resolved Issues:** Move the entire folder to `issues/resolved/`.

*   **Priorities:** Refer to the `priorities.md` at the customer root for the current dashboard.

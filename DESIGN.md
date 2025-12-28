# Implementation Design: Cognitive Perception System

This document provides the concrete implementation blueprint for the **Cognitive Perception Architecture** defined in `ARCHITECTURE.md`. It details the scripts, data flows, and state management required to build the "Super-Context" engine.

## 1. System Components

### A. Data Fetchers (The "Limbs")
Scripts that synchronize remote data to local JSON caches.

1.  **Task Sync Tool** (`scripts/sync_tasks.py`):
    *   **Responsibility**: Wraps `ticktick-access` to download all tasks from the designated work project/list.
    *   **Output**: `~/.local/share/agentic-consult/cache/tasks.json`
    *   **Mode**: Can be invoked manually or via `consult refresh`.

2.  **Email Sync Tool** (`scripts/sync_emails.py`):
    *   **Responsibility**: Fetches recent emails and ensures thread completeness.
    *   **Logic**:
        1.  Fetch all messages sent/received in the last `N` days (config: `app.yaml`).
        2.  Extract unique `threadId`s.
        3.  **Thread Completion**: Fetch *all* messages for those threads (even if older than `N` days) to ensure conversation continuity.
        4.  **Deduplication**: Skip messages already present in the local cache.
    *   **Output**: `~/.local/share/agentic-consult/cache/emails.json`

### B. Context Builder (The "Memory Maker")
**Script**: `scripts/update_context_cache.py`

*   **Responsibility**: Bundles local data into a massive context and uploads it to Gemini.
*   **Input**: `tasks.json` (full history) + `emails.json` (rolling window of threads).
*   **Action**:
    1.  Reads local JSON caches.
    2.  Formats them into a text/structured representation optimized for LLM reading.
    3.  Calls Gemini API to create/update a **Context Cache**.
    4.  Saves the `cache_name` (resource ID) and `last_updated_timestamp` to `workflow_state.json`.

### C. Cognitive Tool (The "Brain")
**MCP Tool**: `get_situational_awareness` (or `consult analyze`)

*   **Responsibility**: The high-level reasoning engine exposed to the Primary Agent.
*   **Logic (The Hybrid Strategy)**:
    1.  **Read State**: Load `cache_name` and `last_updated_timestamp` from `workflow_state.json`.
    2.  **Fetch Deltas**:
        *   Identify tasks modified > `last_updated_timestamp`.
        *   Identify emails received > `last_updated_timestamp`.
    3.  **Construct Prompt**:
        *   *System*: "You are a prioritization assistant."
        *   *Context*: [Reference `cache_name`]
        *   *User*: "Here are the NEW items since cache creation: [Insert Deltas]. Question: [User Query]"
    4.  **Execute**: Send to Gemini API.
    5.  **Return**: The synthesized answer.

## 2. State Management Schema (`workflow_state.json`)

```json
{
  "context_cache": {
    "resource_name": "cachedContents/12345abcdef",
    "created_at": "2024-12-27T08:00:00Z",
    "expiration": "2024-12-27T20:00:00Z",
    "content_snapshot": {
      "tasks_hash": "sha256...",
      "last_email_id": "msg_98765"
    }
  },
  "last_sync": {
    "tasks": "2024-12-27T10:00:00Z",
    "emails": "2024-12-27T10:05:00Z"
  }
}
```

## 3. Alignment with Architecture

This design strictly implements the **Hub-and-Spoke** pattern from `ARCHITECTURE.md`:
*   **Hub**: `consult analyze` (The Cognitive Tool).
*   **Spokes**: `sync_tasks.py` and `sync_emails.py`.
*   **Pattern**: It uses the **Hybrid Delta Caching** strategy to balance freshness (deltas) with depth (cached history).

## 4. Implementation Priorities

1.  **Refine `gwsa`**: Ensure `gwsa` exposes a "Thread Fetch" capability efficiently.
2.  **Build Sync Scripts**: Create the standalone fetchers.
3.  **Build Context Updater**: Implement the caching logic using `google-genai` SDK.
4.  **Build Cognitive Tool**: Wire it all together in the MCP server.

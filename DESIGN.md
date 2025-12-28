# Implementation Design: Cognitive Perception System

## 0. Current Implementation Status (Aspirational)
*As of Dec 2025*

| Component | Status | Notes |
| :--- | :--- | :--- |
| **Data Retrievers** | 🚧 Partial | `consult refresh` exists but logic is coupled. Needs extraction to standalone scripts. |
| **Context Pipeline** | ❌ Missing | No logic yet for bundling data into Gemini Context Cache. |
| **Reasoning Engine** | ❌ Missing | `consult analyze` tool needs to be built. |
| **State Management** | ❌ Missing | `workflow_state.json` schema defined but not implemented. |

---

This document provides the concrete implementation blueprint for the **Cognitive Perception Architecture** defined in `ARCHITECTURE.md`. It details the scripts, data flows, and state management required to build the "Super-Context" engine.

## 1. System Components

### A. Data Retrievers (The "Limbs")
Scripts that synchronize remote data to local JSON caches. These should be exposed as **both** CLI commands (for manual/cron use) and **MCP Tools** (so the Agent can trigger a refresh autonomously).

1.  **Task Sync Tool** (`scripts/sync_tasks.py`):
    *   **Responsibility**: Wraps `ticktick-access` to download all tasks from the designated work project/list.
    *   **Output**: `~/.local/share/agentic-consult/cache/tasks.json`
    *   **Mode**: CLI (`consult sync tasks`) and MCP Tool (`sync_tasks`).

2.  **Email Sync Tool** (`scripts/sync_emails.py`):
    *   **Responsibility**: Fetches recent emails and ensures thread completeness.
    *   **Logic**:
        1.  Fetch all messages sent/received in the last `N` days (config: `app.yaml`).
        2.  Extract unique `threadId`s.
        3.  **Thread Completion**: Fetch *all* messages for those threads (even if older than `N` days) to ensure conversation continuity.
        4.  **Deduplication**: Skip messages already present in the local cache.
    *   **Output**: `~/.local/share/agentic-consult/cache/emails.json`
    *   **Mode**: CLI (`consult sync emails`) and MCP Tool (`sync_emails`).

### B. Context Ingestion Pipeline (The "Memory Maker")
**Script**: `scripts/update_context_cache.py`

*   **Responsibility**: Bundles local data into a massive context and uploads it to Gemini.
*   **Input**: `tasks.json` (full history) + `emails.json` (rolling window of threads).
*   **Action**:
    1.  Reads local JSON caches.
    2.  Formats them into a text/structured representation optimized for LLM reading.
    3.  Calls Gemini API to create/update a **Context Cache**.
    4.  Saves the `cache_name` (resource ID) and `last_updated_timestamp` to `workflow_state.json`.

### C. Reasoning Engine (The "Brain")
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
        *   *User*: "Here are the NEW items since cache creation (Working Memory): [Insert Delta]. Question: [User Query]"
    4.  **Execute**: Send to Gemini API.
    5.  **Return**: The synthesized answer.

### D. Performance Strategy & Future-Proofing

We prioritize **capability over raw speed**, relying on the rapid evolution of Gemini models to solve latency.

*   **Latency Target:** 5-15 seconds (Model dependent).
*   **Model Tiering:**
    *   **Quick Checks** (`--fast`): Use `gemini-*-flash` (Target <5s) for simple summarization.
    *   **Deep Planning** (`--deep`): Use `gemini-*-pro` (Target <20s) for complex cross-referencing.
*   **Optimization:** We do *not* prematurely optimize code for <1s latency. We rely on Google's infrastructure improvements (Gemini 2.0/3.0) to accelerate the "Reasoning Engine" over time.

### E. Network Feasibility Analysis

Standard internet connections (e.g., 250 Mbps Down / 10 Mbps Up) are sufficient and **not a bottleneck**.

*   **Context Upload (5MB / 500k tokens):** ~4 seconds (Background operation).
*   **Delta Query (80KB / 20k tokens):** < 0.1 seconds (Interactive operation).
*   **Conclusion:** Transport latency is negligible. User-perceived latency is dominated by Server-Side Inference (TTFT + Generation). We focus optimizations on **Prompt Structure**, not Payload Size.

### F. Cloud Colocation Analysis (Thought Experiment)

Comparing execution on **Local Laptop** (250 Mbps) vs. **GCE Instance** (20 Gbps):

*   **Current State:**
    *   *Local:* 4s Upload + 10s Inference = 14s Total.
    *   *Cloud:* 0.1s Upload + 10s Inference = 10.1s Total.
    *   *Result:* ~25% improvement. Noticeable, but not transformative for text agents.
*   **Future State (10x Faster LLMs):**
    *   *Local:* 4s Upload + 1s Inference = 5s Total.
    *   *Cloud:* 0.1s Upload + 1s Inference = 1.1s Total.
    *   *Result:* ~80% improvement. **Cloud Colocation becomes critical** once inference latency drops below transport latency.

### G. Local Inference (Gemma) Assessment

Running open models (e.g., Gemma 2) locally is **Rejected / Not Recommended**.

*   **Constraint:** Local context windows (8k-32k) are insufficient for the "Super-Context" strategy (500k+ tokens).
*   **Impact:** Using local inference would force a regression to **Vector RAG** (Fragmented Retrieval), breaking the core architectural decision to prioritize "Holistic Reasoning."
*   **Verdict:** The capability loss outweighs the privacy/cost benefits for this specific "Executive Assistant" persona.

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
*   **Hub**: `consult analyze` (The Reasoning Engine).
*   **Spokes**: `sync_tasks.py` and `sync_emails.py`.
*   **Pattern**: It uses the **Hybrid Delta Caching** strategy to balance freshness (deltas) with depth (cached history).

## 4. Alignment with Industry Standards

Our design maps to several established AI and software patterns:

1.  **Context Ingestion Pipeline**: Derived from standard **ETL (Extract-Transform-Load)** and **RAG Ingestion** patterns. We treat unstructured emails/tasks as raw data to be cleaned and structured for LLM consumption.
2.  **Reasoning Engine**: Aligns with the **"Agentic Tool-Use"** and **"Cognitive Architecture"** patterns (e.g., as seen in LlamaIndex or OpenAI Assistant API). We encapsulate the *thinking* about a domain within the tool itself.
3.  **Working Memory (Delta)**: Based on the **Memory-Augmented Neural Network** theory (and implementations like MemGPT). We distinguish between "Long-term" (Cache) and "Short-term/Working" (Prompt Delta) storage.
4.  **Hub-and-Spoke**: A traditional **Enterprise Service Bus (ESB)** or **Orchestrator** pattern applied to autonomous agents.

## 5. Transition Plan: Concrete Implementation Steps

To reach the target state, the following refactoring and development steps are required:

### Step 1: Logic Decoupling (Retrievers)
-   Extract email fetching logic from `agentic_consult/refresh.py`.
-   Move to a new package: `agentic_consult/retrievers/`.
-   Implement `scripts/sync_emails.py` as a standalone command-line entry point.
-   **Register** `sync_tasks` and `sync_emails` as tools in `agentic_consult/mcp/server.py`.

### Step 2: State Management Infrastructure
-   Implement `agentic_consult/processing_state.py` to manage `workflow_state.json`.
-   This module will provide atomic read/update operations for the `context_cache` metadata.

### Step 3: The Ingestion Pipeline
-   Develop `agentic_consult/pipeline/` package.
-   Implement `update_context_cache.py`:
    -   Logic to read `emails.json` and `tasks.json`.
    -   Formatting logic to convert JSON records into optimized prompt text.
    -   API integration with `google-genai` for cache creation.

### Step 4: The Reasoning Engine (MCP Tool)
-   Implement `agentic_consult/engine/` package.
-   Create the `analyze` tool logic:
    -   Logic to compute deltas based on timestamps in `workflow_state.json`.
    -   Prompt engineering for the "Chief of Staff" persona.
-   Register the tool in `agentic_consult/mcp/server.py`.

### Step 5: CLI Re-composition
-   Refactor `agentic_consult/cli/refresh.py` into a **Coordinator**.
    -   Remove embedded logic.
    -   Implement orchestration: Call `retrievers` -> Call `pipeline` -> Update State.
-   Add `consult analyze` command as the entry point for the Reasoning Engine.

## 6. Optimization: Cost-Aware Planning

To prevent redundant operations and excessive latency, we implement **Cost-Aware Planning** in the orchestration layer.

### A. Semantic Metadata (Docstrings)
We explicitly annotate heavy tools (like `sync_emails`) with performance warnings. This teaches the LLM that these tools have a high "cost" in terms of time and API quota.

**Example**:
> "PERFORMANCE NOTE: This operation takes 15-45 seconds. Do not call more than once per session."

### B. Logic Guardrails (Freshness Checks)
The Python implementation of the tools enforces a rate limit based on the `last_sync` timestamps in `workflow_state.json`.

**Behavior**:
-   If a sync tool is called and the data is < 5 minutes old, the tool returns immediately with a message: *"Skipped sync: Cache is fresh (updated N mins ago)."*
-   This feedback loop prevents the LLM from "spamming" heavy operations while still allowing the tool to be called autonomously when necessary.

## 7. Customer Issues Integration (Episodic Memory)

The existing `issues/` directory serves as the **Episodic Memory** (or Topic Memory) for the agent.

### Integration Strategy
*   **Ingestion:** The **Context Ingestion Pipeline** (`update_context_cache.py`) recursively reads all Markdown files in `issues/`.
*   **Role:** These files provide the qualitative context ("Why we decided X", "Customer constraints Y") that is missing from structured Task/Email data.
*   **Persistence:** These files are **not** replaced or deleted by the pipeline. They are treated as the "Source of Truth" for narrative history.
*   **Prompting:** The content of active issues is prioritized in the "Context Brief" synthesis.

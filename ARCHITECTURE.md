# Architectural Vision & Decision Records

This document captures the foundational theory, architectural patterns, and strategic trade-offs chosen for the `agentic-consult` toolkit. It serves as an Architecture Decision Record (ADR) to explain *why* specific paradigms were chosen over industry-standard alternatives.

## 1. Core Vision: The Cognitive Perception Architecture

The goal is to evolve from a "chatbot with tools" not into a rigid script-runner, but into a **highly situational, context-aware partner**. We aim to give the Primary Agent (Gemini CLI) "Super-Senses"—the ability to instantly perceive, synthesize, and reason about massive amounts of historical data (emails, tasks, code) without being overwhelmed by it.

## 2. Core Design Pattern: Cognitive Tools (The Perception Layer)

We utilize a **Cognitive Tool** pattern. Instead of the Primary Agent managing low-level data fetching, we expose "Smart Views" via tools.

-   **The Hub (Orchestrator)**: The Gemini CLI (You + LLM). It holds the initiative and high-level reasoning.
-   **The Spokes (Perception Engines)**: Specialized modules/MCP tools (`ticktick-access`, `gwsa`) that act as "Sensors".
    *   *Input:* High-level intent ("What is the status of Project X?").
    *   *Process:* The tool accesses its cached "Long-Term Memory" (Gemini Context Cache) to analyze thousands of records.
    *   *Output:* A synthesized **Situation Report** (not raw data). "Project X is waiting on Alice. Last email was 2 days ago. Related task #102 is overdue."

### Why this reduces complexity:
*   **Decoupling:** The Primary Agent doesn't need to know *how* to filter TickTick tasks or parse Gmail threads. It just asks for a summary.
*   **Stability:** We avoid complex "Agent Swarms" or rigid "Workflow Scripts" (`orchestrator.py`) that break easily. The intelligence lives in the *tool's response*, empowering the LLM to make the final decision.

## 3. Division of Labor: CLI vs. API

It is critical to distinguish between the **Gemini CLI** (the user interface) and the **Gemini API** (the backend intelligence).

| Role | **Gemini CLI (Primary Agent)** | **Gemini API (Cognitive Tools)** |
| :--- | :--- | :--- |
| **Function** | **The CEO / Orchestrator** | **The Analyst / Deep Memory** |
| **Context** | **Dynamic & Small.** Focused on the active conversation, immediate intent, and synthesized summaries. | **Static & Massive.** Holds 500k+ tokens of project history, logs, and emails via Context Caching. |
| **Interaction** | Multi-turn conversation with the user. | Single-shot queries ("Reason over this data and answer X"). |
| **Constraint** | Expensive/Slow to reload massive context on every turn. | Cheap/Fast to query once cached. |

**The Strategy:**
We use the **API** (via Python scripts exposed as Tools) to do the heavy lifting of reading/reasoning over massive datasets. We use the **CLI** to receive the distilled insights and make the final decision. This avoids "Context Pollution" where the active agent becomes overwhelmed, slow, and expensive.

## 4. The Paradigm: Long-Context Native vs. Vector RAG

The most significant architectural choice is the use of **Google Gemini Context Caching** instead of traditional **Vector Search (RAG)**.

| Feature | Traditional RAG (Vector DB) | Long-Context Native (Caching) |
| :--- | :--- | :--- |
| **Data Visibility** | Fragmented (top-k chunks only) | Holistic (the entire dataset) |
| **Reasoning** | Localized to specific keywords | Global (connects dots across time) |
| **Complexity** | High (Embeddings, Indexing, Retrieval) | Low (Direct data upload to model) |
| **Performance** | Variable (depends on retrieval quality) | Consistent (model "sees" everything) |

### Decision: Holistic Reasoning
We chose Long-Context Native because personal productivity (summarizing a project's evolution, finding subtle threads across months) requires **Global Reasoning**. Vector Search often misses the logical relationship between tasks/emails that are semantically similar but chronologically or logically distinct.

### Strategy: Hybrid Delta Caching
Since Gemini Context Caches are immutable, we use a hybrid strategy to balance freshness with cost/latency.

1.  **The "Super-Context" (Cold Cache)**:
    *   **Content**: A unified massive context containing Task History (TickTick), Email History (GWSA), and Project Notes.
    *   **Management**: Rebuilt periodically (e.g., nightly).
    *   **Rolling Window Optimization**:
        *   *Tasks*: Active/Pending (All) + Completed (Last 90 days) + Summarized Archive (Older).
        *   *Emails*: Recent Threads (Last 14 days) + VIP History (Last 30 days).
    *   **Benefit**: Enables cross-domain reasoning (e.g., linking an old task to a new email thread) without re-uploading 50k tokens per query.

2.  **The "Hot Delta" (Prompt Injection)**:
    *   **Concept**: Data changed *since* the cache was built.
    *   **Mechanism**: The Cognitive Tool fetches small lists of new/modified items (created > `T_cache_creation`) from local DBs/APIs.
    *   **Injection**: These are appended to the user's prompt *alongside* the cache reference.
    *   **Result**: The model sees the stable history (Cache) + the latest updates (Prompt) and merges them logically.

## 5. Framework Selection: Custom Orchestration vs. LangGraph/Frameworks

We avoid heavy-weight frameworks like LangGraph, Semantic Kernel, or CrewAI.

-   **Decision**: Lean Python + MCP.
-   **Rationale**: 
    -   **Performance**: Direct API calls have lower latency than framework abstraction layers.
    -   **Control**: Explicit state management in Python is easier to debug than complex directed-acyclic-graphs (DAGs) in third-party libraries.
    -   **First-Class Tooling**: MCP (Model Context Protocol) is the native plugin format for our primary interfaces. Using MCP ensures our "Cognitive Tools" are portable to any client (CLI, IDE, or Desktop Agent).

## 6. Patterns to Study & Apply

To improve effectiveness without adding complexity, focus on these patterns:

1.  **The "Cognitive Tool" (or Reasoning Tool):**
    *   *Concept:* A tool that doesn't just "do" (like `write_file`), but "thinks" (like `analyze_project_history`). It uses a cheaper/faster LLM call internally to process data before returning a result.
    *   *Application:* Build a `get_situational_awareness()` tool that polls your Task and Email engines and returns a prioritized "Morning Briefing" automatically.

2.  **The "Semantic Router":**
    *   *Concept:* Instead of hardcoding "If X then Y", let the LLM decide which "Expert Tool" to call based on the user's intent.
    *   *Application:* Your CLI already does this natively. Trust the model to pick the right tool (`backup_local_repo`, `run_precommit_scan`, `analyze_files`) rather than forcing it into a linear script.

3.  **Context Isolation:**
    *   *Concept:* Keep the Primary Agent's context window clean. Never dump raw logs or 500 emails into the main chat. Always synthesize first.
    *   *Application:* Ensure every "List" or "Search" tool has a summarization step (or default limit) so the Primary Agent receives actionable insights, not noise.

## 7. Session Continuity & Initiative

To enable a "Day 1 / Minute 1" experience where the agent immediately takes initiative, we rely on three pillars:

1.  **`GEMINI.md` (The Bootloader)**: Defines the *Persona* ("Chief of Staff") and the *Protocol* ("Upon startup, always call `get_situational_awareness` first"). It sets the mission but contains no dynamic state.
2.  **`workflow_state.json` (The Bookmark)**: Persists the execution context across sessions (e.g., `last_sync_time`, `current_focus_project`, `pending_decisions`).
3.  **`get_situational_awareness` (The Bridge)**: A Cognitive Tool that reads the Bookmark and queries the Super-Context to generate a real-time briefing.
    *   *Effect:* The agent wakes up, reads its instructions, checks the state, and immediately asks: "Welcome back. We were working on Project X. 3 new emails have arrived since. Shall we resume?"
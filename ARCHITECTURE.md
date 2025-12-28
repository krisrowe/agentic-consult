# Architectural Vision & Decision Records

This document captures the foundational theory, architectural patterns, and strategic trade-offs chosen for the `agentic-consult` toolkit. It serves as an Architecture Decision Record (ADR) to explain *why* specific paradigms were chosen over industry-standard alternatives.

## 1. Core Vision: The Semi-Autonomous Workflow Orchestrator

The goal is to evolve beyond a simple "chatbot with tools" into a stateful, semi-autonomous engine that proactively triages inputs (Emails, Tasks) by synthesizing them against massive historical context.

## 2. Core Design Pattern: Hierarchical (Hub-and-Spoke)

We utilize a **Supervisor-Worker (Hierarchical)** pattern rather than a "Swarm" or "OS Agent" approach.

-   **The Hub (Supervisor)**: The `agentic-consult` CLI orchestrates the high-level workflow (Fetch -> Synthesize -> Interact).
-   **The Spokes (Workers)**: Specialized modules/MCP tools (`ticktick-access`, `gwsa`) that act as "Cognitive Tools" with deep domain knowledge and specialized memory.
-   **Why?**: Reliability and Control. Hierarchical agents are less prone to logical loops and "hallucination drift" than autonomous swarms, making them more suitable for high-stakes professional productivity.

## 3. The Paradigm: Long-Context Native vs. Vector RAG

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
Since Gemini Context Caches are immutable, we use a hybrid strategy:
1.  **Cold Cache**: A large, stable cache of historical data (e.g., all tasks/emails up to T-minus-24h).
2.  **Hot Delta**: New or modified items are injected directly into the prompt alongside the Cache ID.
3.  **Re-Commit**: The cache is rebuilt on a schedule (e.g., nightly) to incorporate the deltas.

## 4. Framework Selection: Custom Orchestration vs. LangGraph/Frameworks

We avoid heavy-weight frameworks like LangGraph, Semantic Kernel, or CrewAI.

-   **Decision**: Lean Python + MCP.
-   **Rationale**: 
    -   **Performance**: Direct API calls have lower latency than framework abstraction layers.
    -   **Control**: Explicit state management in Python is easier to debug than complex directed-acyclic-graphs (DAGs) in third-party libraries.
    -   **First-Class Tooling**: MCP (Model Context Protocol) is the native plugin format for our primary interfaces. Using MCP ensures our "Cognitive Tools" are portable to any client (CLI, IDE, or Desktop Agent).

## 5. Implementation Roadmap

1.  **Synthesizer Phase**: A pre-computation step where the Hub queries all Spokes in parallel to generate a "Context Brief" for new inputs.
2.  **Context Isolation**: The Primary Agent's context window remains clean, receiving only the synthesized brief rather than raw data dumps, ensuring high reasoning quality and low token costs.
3.  **Reactive Refresh**: Use local caches (XDG cache) and file-based state (`workflow_state.json`) to track process positioning and synchronization timestamps.

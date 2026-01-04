# Implementation Design: Cognitive Perception System

## 0. Current Implementation Status
*As of Dec 2025*

| Component | Status | Notes |
| :--- | :--- | :--- |
| **Data Retrievers** | 🚧 Partial | `consult refresh` exists but logic is coupled. Needs extraction to standalone scripts. |
| **Context Pipeline** | 🚧 Partial | `consult gemini` and `analyze_files` tool provide ad-hoc context bundling. |
| **Reasoning Engine** | ✅ Implemented | `consult gemini` (CLI) and `analyze_files` (MCP) are the entry points. |
| **State Management** | 🚧 Partial | `emails_processed.txt` and delta archiving implemented. |

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
**Script**: `agentic_consult/context.py`

*   **Responsibility**: Bundles local data into a formatted context for Gemini.
*   **Input**: Files, directories, and exclusion patterns.
*   **Action**:
    1.  Recursively walks directories.
    2.  Filters based on `.gitignore` style patterns.
    3.  Skips binary files and enforces size limits.
    4.  Formats into a structured representation with path headers.

### C. Reasoning Engine (The "Brain")
**MCP Tool**: `analyze_files` (or `consult gemini`)

*   **Responsibility**: The high-level reasoning engine exposed to the Primary Agent.
*   **Logic (The Hybrid Strategy)**:
    1.  **Collect Context**: Load files specified in the prompt or tool call.
    2.  **Apply Exclusions**: Filter out noise (logs, binary, artifacts).
    3.  **Construct Prompt**:
        *   *Context*: [Concatenated file content with headers]
        *   *User*: [User Question]
    4.  **Execute**: Send to Gemini API.
    5.  **Return**: The synthesized answer.

### D. Performance Strategy & Future-Proofing

We prioritize **capability over raw speed**, relying on the rapid evolution of Gemini models (2.5/3.0 series) to solve latency.

*   **Latency Target:** 5-15 seconds (Model dependent).
*   **Model Tiering:**
    *   **Quick Checks** (`--fast`): Use **Gemini 3.x Flash** (Target <5s) for simple summarization.
    *   **Deep Planning** (`--deep`): Use **Gemini 3.x Pro** (Target <20s) for complex cross-referencing.
*   **Optimization:** We do *not* prematurely optimize code for <1s latency. We rely on Google's infrastructure improvements to accelerate the "Reasoning Engine" over time.

### E. Network Feasibility Analysis

Standard coaxial internet connections (e.g., 250 Mbps Down / 10 Mbps Up) are sufficient and **not a bottleneck**.

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

### G. Local Inference (Gemma 3) Assessment

With the release of **Gemma 3** (128k Context), local inference is **Viable for Lite Mode**.

*   **Constraint:** 128k tokens is sufficient for a "Rolling Window" (weeks) but not the full "Super-Context" (years).
*   **Verdict:** We maintain a **Cloud-First** architecture to leverage the 1M+ context window of Gemini Pro/Flash (2.5/3.0), but acknowledge Gemma 3 as a valid fallback for offline or strictly private sessions.

#### G.2 Private Cloud Inference (GCE) Assessment

Renting custom GPU VMs (e.g., A100/L4 instances) to run Gemma 3 on Google Cloud is **Rejected.**

*   **Cost:** GPU-enabled instances are significantly more expensive than the managed Gemini API for the same token throughput.
*   **Complexity:** Requires managing container runtimes, model serving (TGI/vLLM), and auto-scaling logic.
*   **Verdict:** **"Worst of both worlds."** High cost and high maintenance for no performance gain over the managed API. The only benefit is data sovereignty, which is a low priority for this project.

### H. Cost Analysis & Mitigation

To maintain the "Executive Assistant" capability without excessive cost (approx. $200/mo for pure Pro usage), we adopt a **Flash-First Strategy**:

1.  **Default Engine:** **Gemini 3.x Flash**.
    *   *Capability:* Excellent at summarization and extraction over large context.
    *   *Cost:* Approx. **1/10th to 1/20th** the price of Pro.
    *   *Estimated Bill:* **$10 - $30 / month** for daily professional usage.
2.  **Escalation Engine:** **Gemini 3.x Pro**.
    *   *Trigger:* Explicit user request (`--deep`) or complex multi-domain reasoning tasks.
    *   *Role:* The "Senior Analyst" brought in only for high-stakes problem solving.

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

## 8. Google Workspace Authentication Strategy

### Decision: gwsa as the Auth Management Layer

We use [gworkspace-access (gwsa)](https://github.com/krisrowe/gworkspace-access) as our Google Workspace authentication and access layer, rather than direct ADC (Application Default Credentials) with optional overrides.

### Alternatives Considered

1. **Direct ADC with fallback**: Use `google.auth.default()` directly, allowing users to configure via `gcloud auth application-default login` or custom `GOOGLE_APPLICATION_CREDENTIALS`.

2. **gwsa as required dependency**: Require gwsa to be installed and configured (`gwsa profiles add`) before agentic-consult email features work.

### Why We Chose gwsa

Direct ADC fallback was rejected due to **unpredictable user experience**:

- **No profile management**: ADC is single-identity. Many users have multiple Google accounts (personal, work, rental properties). gwsa provides `profiles add/use/list` for clean multi-identity workflows.

- **No scope validation**: ADC silently fails or returns partial data when scopes are insufficient. gwsa validates scopes during profile setup and provides clear error messages.

- **No token status tracking**: With ADC, users discover auth problems at runtime via cryptic API errors. gwsa provides `profiles current` and `status` commands for proactive health checks.

- **Mysterious errors**: When ADC-based auth fails (expired tokens, wrong project, missing scopes), debugging requires understanding Google Cloud internals. gwsa centralizes auth state and provides actionable diagnostics.

- **Client ID complexity**: Using ADC with custom OAuth client IDs (required for some restricted accounts) involves manual credential file management. gwsa abstracts this behind `client set` and `profiles add`.

### Trade-off Acknowledged

This decision **adds a setup step** for users: they must run `gwsa profiles add` before email tools work. We accept this trade-off because:

1. The setup is a one-time operation with clear interactive prompts
2. Multi-profile support is essential for the target use case (personal + work accounts)
3. Auth failures surface early (at setup) rather than mysteriously at runtime
4. The gwsa MCP server provides the same auth context to other agents

### Future Consideration

If gwsa adds an ADC fallback mode with proper validation (scope checking, token status, clear error messages), we could revisit making auth setup optional. Until then, explicit `gwsa profiles add` remains the required path.

## 9. Future: Bill Payment Tracking (`process_bills`)

### Concept

A `process_bills` MCP tool analogous to `process_email`:

- **Rules-based**: Configure expected recurring bills (water, electric, insurance, etc.) with due dates and amounts
- **Monarch integration**: Check transactions to verify payments were made
- **Proactive alerts**: If expected payment not found by threshold date, prompt user
- **Better than email**: Monarch transactions are more reliable than payment confirmation emails

### Why This Matters

Recurring bills without auto-pay (e.g., water bills for rental properties) are easy to forget. Email confirmations can be missed or delayed. Checking Monarch for the actual transaction is definitive.

### Potential Schema

```yaml
bills:
  - id: clement-water
    payee: "Marshall County Water"
    amount_range: [40, 80]
    due_day: 15
    check_by_day: 8
    account_hint: "Ally Checking"
```

### Status

Not implemented. Tracking here for future consideration.

## 10. Public vs Personal Workflows

### Design Principle

agentic-consult provides **reusable workflow mechanisms** that make sense to abstract. Some workflows are too personal/opinionated to belong here.

**Belongs in agentic-consult (public):**
- Workflows around universal tools (email, calendar, git)
- Mechanisms others would realistically adopt
- Config schemas that work across different users' data

**Belongs in user's private config repo:**
- Workflows built on niche tool choices others won't adopt
- Processes too opinionated to abstract
- When the effort to generalize wouldn't pay off

**The test:** Would someone install your tool stack just to use this workflow?
- Email processing: Yes - everyone has email, Gmail is common
- Niche finance app integration: No - nobody adopts a finance tool for one workflow

### Relationship to Config Repos

agentic-consult is designed to work with private "config repos" that hold:
- User-specific rule configs (email.yaml, etc.)
- Personal workflow definitions that aren't worth abstracting
- Context docs (like CLAUDE.md) with personal details

The public repo provides mechanisms; private repos provide configs and personal workflows.

### Framework Role for Personal Workflows

**Open question:** Should agentic-consult provide a registry of workflows (both public and personal) that suggests what the user should periodically do?

**Potential value:** A unified list of things the agent can help with - standard workflows (process_email) alongside personal ones (check water bills). Suggest them at the right cadence. Remind the user what's available.

**Current stance:** Wait for the need to evolve. We haven't identified what this would look like yet. Let it emerge from usage.

### Workflow Tool Pattern

All workflow tools (public reusable or private/workspace-specific) follow a common pattern:

1. **Naming**: `process_*` (e.g., `process_email`, `process_bills`)

2. **Behavior**:
   - Read config file (e.g., `email.yaml`, `bills.yaml`)
   - Load a prompt/instructions template
   - Inject user rules and context into template
   - Return instructions as MCP tool response

3. **Docstring Pattern**:
   > "Invoke this tool and follow the instructions it provides."

4. **Registry & Scheduling**:
   - All workflow tools (public and private) must be listable via a registry
   - Each entry includes: suggested cadence (daily, weekly, monthly), timing hints, triggers
   - Example: `process_email` → daily; `process_bills` → weekly on the 8th
   - The agent can query the registry to suggest what workflows to run in a session

5. **Framework Role**:
   - agentic-consult provides the **template loading** and **config merging** mechanisms
   - agentic-consult provides **base templates** for public workflows
   - Private repos provide **rule configs** (what to match, what to do)
   - Private repos may provide **custom templates** for personal workflows
   - The agent orchestrates by calling the tool and executing the returned instructions

This pattern ensures workflow tools are declarative (config-driven) rather than imperative, letting the agent reason about the instructions rather than executing hardcoded logic.

### Open Question: Rule Management & Configuration Discovery

Workflow tools that support user-configurable rules (like `process_email` with `email.yaml`) raise the question: how does the user discover they can configure rules, and when should the agent suggest it?

**Options being explored:**
1. **Kernel injection**: The shared system prompt (KERNEL.md) instructs agents to look for `*_rules` or `add_*_rule` companion tools and suggest configuration when patterns emerge (e.g., "I noticed you archived 5 similar emails - want me to add a rule?")
2. **Docstring-driven**: Each workflow tool's docstring explains configuration options; agent uses reasoning to surface them at appropriate times
3. **Per-workflow tools**: Each workflow provides its own rule management tools; discovery is implicit through tool listing

**Current stance:** Not yet implemented. The framework may eventually inject guidance via KERNEL.md telling agents to proactively discover configuration tools and suggest them. For now, we rely on agents reading tool descriptions and using judgment.

### Session Bootstrap: `guide_user` Tool

**Concept:** A tool the agent invokes at session start to get personalized workflow suggestions.

**Possible names:**
- `guide_user` - what should we do today?
- `introduce_workflows` - what's available?
- `get_session_agenda` - what's due?

**What it returns:**
- List of registered workflows with cadence (daily/weekly/monthly)
- Which are "due" based on last run timestamp
- Natural language greeting: "Good morning! Shall we process emails? Your weekly backup check is also due."

**Bootstrap mechanism:**
- KERNEL.md includes instruction: "On new session, invoke `mcp__consult__guide_user` to see what workflows are suggested"
- Agent follows the instruction, tool returns agenda, agent presents to user
- MCP servers can't push proactively; this relies on agent following kernel instructions

**IMPORTANT: SessionStart Hooks Available in Both CLIs**

Both Gemini CLI and Claude Code support `SessionStart` hooks that can initialize workflows at session start. This is the key integration point for `guide_user`.

**Gemini CLI** (`.gemini/settings.json`):
```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [
          {
            "name": "init-workflows",
            "type": "command",
            "command": "consult guide-user --json",
            "description": "Initialize Smart Workflow Assistant"
          }
        ]
      }
    ]
  }
}
```

**Claude Code** (`.claude/settings.json`):
```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "consult guide-user"
          }
        ]
      }
    ]
  }
}
```

Both can inject context via stdout or `additionalContext` in JSON output. The hook runs at session start and the output becomes part of the agent's initial context.

**Implementation TODO:**
- [ ] Create `consult guide-user` CLI command that outputs workflow agenda
- [ ] Test SessionStart hook integration in both Gemini CLI and Claude Code
- [ ] Document hook setup in agentic-consult README

References:
- Gemini CLI: https://geminicli.com/docs/hooks/writing-hooks/#configuration
- Claude Code: https://docs.anthropic.com/en/docs/claude-code/hooks#sessionstart

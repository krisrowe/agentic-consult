# Implementation Design: Cognitive Perception System

## 0. Current Implementation Status
*As of Jan 2026*

| Component | Status | Notes |
| :--- | :--- | :--- |
| **Data Retrievers** | ❌ Missing | Systematic `sync_tasks` and `sync_emails` scripts are not implemented. |
| **Context Pipeline** | 🚧 Partial | `consult gemini` and `analyze_files` tool provide ad-hoc context bundling. |
| **Reasoning Engine** | ✅ Implemented | `consult gemini` (CLI) and `analyze_files` (MCP) are the entry points. |
| **State Management** | 🚧 Partial | `emails_processed.txt` and delta archiving implemented. |

---

This document provides the concrete implementation blueprint for the **Cognitive Perception Architecture** defined in `ARCHITECTURE.md`. It details the scripts, data flows, and state management required to build the "Super-Context" engine.

## 1. System Components

### A. Data Retrievers (The "Limbs")
Scripts that synchronize remote data to local JSON caches for **systematic preservation and search**.
*   *Current State:* `triage_emails` caches fetched emails ad-hoc for the duration of a triage session, but does not build a persistent, searchable "Super-Context" database.
*   *Planned State:* Standalone scripts exposed as CLI commands and MCP Tools.

1.  **Task Sync Tool** (Planned):
    *   **Responsibility**: Wraps `ticktick-access` to download all tasks from the designated work project/list.
    *   **Output**: `~/.local/share/agentic-consult/cache/tasks.json`
    *   **Mode**: CLI (`consult tasks sync`) and MCP Tool (`sync_tasks`).

2.  **Email Sync Tool** (Planned):
    *   **Responsibility**: Fetches recent emails and ensures thread completeness.
    *   **Logic**:
        1.  Fetch all messages sent/received in the last `N` days (config: `app.yaml`).
        2.  Extract unique `threadId`s.
        3.  **Thread Completion**: Fetch *all* messages for those threads (even if older than `N` days) to ensure conversation continuity.
        4.  **Deduplication**: Skip messages already present in the local cache.
    *   **Output**: `~/.local/share/agentic-consult/cache/emails.json`
    *   **Mode**: CLI (`consult email sync`) and MCP Tool (`sync_emails`).

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

### I. Prompt Engineering & Context Strategy

We adopt a **Hybrid Strategy** for instructing agents on tool usage, balancing reliability against token cost.

1.  **Docstrings (The Contract):**
    *   **Role:** Define the *capability* and the *expected behavior* permanently in the system prompt.
    *   **Content:** "This tool returns invites... Agent MUST check availability...".
    *   **Why:** Ensures the agent understands the tool's purpose *before* calling it. Essential for correct tool selection and planning.

2.  **Runtime Responses (The Trigger):**
    *   **Role:** Provide immediate **contextual triggers** and reminders in the ephemeral conversation history.
    *   **Content:** "`_Agent: Check your calendar..._`" or specific DSL command blocks (`do accept...`).
    *   **Why:** Prevents "attention decay" in long sessions. Acts as a checklist the agent sees *right now* when the data arrives.

**Evolution Path:**
*   **Current State:** We use both. The redundant runtime instructions ensure 100% reliability with current models (Gemini 2.0 Flash/Pro).
*   **Future State:** As models improve at adhering to complex schemas without prompts, we can slim down the runtime response to pure JSON and rely solely on the docstring contract.

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
- Claude Code: https://docs.anthropic.com/en/docs/claude-code/hooks

## Decision Record: Programmatic Configuration of Email Rule Directives

**Context:**
The email triage system uses a layered configuration model (System -> Bundles -> User) where each layer can `enable` or `disable` rules by pattern. We considered adding MCP tools to programmatically manage these directives (e.g., `add_directive("enable", "work-*")`, `remove_directive("hash...")`).

**Decision:**
**DEFERRED.** We will rely on manual/offline configuration (editing `email.yaml`) for managing rule sets for the foreseeable future.

**Rationale:**
1.  **Complexity vs. Value:** Implementing tools to manage a stack of state directives introduces significant complexity. We would need to:
    *   Track provenance (which file set the directive?).
    *   Implement logic to "override" or "remove" directives that might exist in read-only system files.
    *   Generate stable IDs (hashing) for UI/manipulation.
    *   Handle merge conflicts and ordering nuances.
    This is excessive for a feature used infrequently (setting up a profile).
2.  **User Experience:** It is simpler and clearer for a user to open `email.yaml` and add `enable: ["work-*"]` than to navigate a complex CLI/tool interface for state management.
3.  **Stability:** Simple file-based configuration is less brittle and easier to debug than state mutation logic.
#sessionstart

## Configuration & Migration Strategy

### Settings Portability
We currently use absolute paths or placeholders in `settings.json` (e.g., `$TOOL_SETTINGS_DIR`). As the tool evolves or is renamed (e.g., `agentic-consult` -> `new-tool`), these paths may become stale.

### Migration Plan
Instead of complex dynamic resolution at runtime for every path, we will implement a **Migration Strategy** for future releases:

1.  **Versioning:** `settings.json` will include a `version` field (or we will check the tool version).
2.  **Migration Command:** A `consult config migrate` (or automatic check on `init`) will handle upgrades.
3.  **Logic:**
    *   Detects old paths (e.g., `~/.config/agentic-consult`).
    *   Moves/Copies data to the new location (e.g., `~/.config/new-tool`).
    *   Rewrites `settings.json` to update paths.
    *   Ensures backup configurations point to the new locations.

This allows us to keep the runtime configuration simple and explicit while providing a safe path forward for renaming or restructuring the project.

## 11. Customer Cloud Integration

This section defines the pattern for linking local customer contexts with Google Drive folders.

### State Management
*   **Local Authority:** The `customer.yaml` (or a lightweight `.cloud` file) in the customer's directory is the source of truth for the `drive_folder_id`.
*   **Verification:** The ID in the local config is treated as a *cached* value. It is not authoritative until validated against the Drive API.

### Tool Behaviors

#### `get_customer_info`
*   **Always Returns Local Path:** If a customer is registered locally, this tool *always* returns the local path, even if cloud sync is broken.
*   **Structured Response:** Returns a structured object separating local and cloud concerns.
    ```json
    {
      "name": "Acme Corp.",
      "slug": "acme",
      "local": {
        "path": "/path/to/customers/acme",
        "notes_path": "/path/to/customers/acme/notes"
      },
      "cloud": {
        "status": "initialized",
        "google_drive_folder_id": "...",
        "guidance": null
      }
    }
    ```
*   **Cloud Statuses:**
    *   `"initialized"`: The ID is present in the local config. This does NOT guarantee the folder exists or is accessible (must be validated by client).
    *   `"missing"`: No ID is configured. Guidance provides instructions to run `register_customer`.

#### `register_customer` (Repair Mode)
*   **Idempotency:** This tool is safe to run repeatedly.
*   **Logic:**
    1.  **Discovery:** Lists subfolders in the configured "Customers" Cloud Root (from `config.yaml`).
    2.  **Matching:** Matches folders against the provided `slug`.
    3.  **Conflict Resolution:**
        *   **0 Matches:** Creates a new folder.
        *   **1 Match:** Uses the existing ID (Self-healing).
        *   **>1 Match:** Returns an error requiring manual intervention.
    4.  **Persistence:** Updates the local config (`customer.yaml` or `.cloud`) with the confirmed ID.

### UX Pattern
The Agent should interpret a missing cloud ID in `get_customer_info` not as a fatal error, but as a prompt to offer a repair action via `register_customer`.

## 12. Strict Git Identity Enforcement Logic

This logic ensures that for every repository, the committer identity is either perfectly consistent with the entire history or explicitly declared via a local configuration.

### 1. Data Retrieval
*   **Impending Email:** Resolved from `git var GIT_AUTHOR_IDENT`. This represents the identity Git will use for the next commit.
*   **Local Email:** Resolved from `git config --local --get user.email`. This represents a deliberate identity declaration for the specific repository.

### 2. Execution Flow

#### **Scenario: Local Configuration is Present**
An explicit local configuration indicates intentional identity management for the repository.
*   **Requirement:** All **unpushed commits** (`git log @{u}..HEAD`) must match the `Local Email`.
*   **Failure:** Returns an error if unpushed work is inconsistent with the configured local identity.
*   **Success:** Returns success if all unpushed work matches.

#### **Scenario: Local Configuration is Missing**
In the absence of a local declaration, the tool enforces 100% historical consistency.
*   **Requirement:** Every commit in the **entire repository history** (`git log --format=%ae`) must match the `Impending Email`.
*   **Default Behavior:** Enforcement is **ENABLED by default**. The `settings.json` file and the specific setting need not exist for enforcement to apply.
*   **Pass:** The repository is pristine (single-user history matching the current environment).
*   **Conflict:** Any scenario where the impending commit author and every existing commit author in the repository history are not all identical.
    *   **Check Override:** Verify if `precommit.git_local_user_identity_optional` is set to `true` in `settings.json`.
    *   **Final Decision:**
        *   If `true`: **PASS** (Enforcement is disabled for the machine).
        *   If `false` (Default/Missing): **FAIL** with guidance.

### 3. Failure Guidance
When a conflict is detected in the "Missing Local Configuration" scenario, the following options are presented:
1.  **Set Local Identity:** `git config user.email <impending_email>`
2.  **Disable Enforcement:** `consult config set precommit.git_local_user_identity_optional true`

## 13. Logging Design Principles

### Transaction-Level INFO Logs

For batch processing (email analyzer, fetcher, etc.), each item processed should have 1-2 INFO log entries:

1. **Before processing**: Brief context about what's being processed
2. **After processing**: Result/outcome

These logs should be:
- **Concise**: One sentence each
- **No PII by default**: Message IDs and dates are OK; subjects/senders require opt-in
- **Not large**: No full payloads or responses

**Purpose**: These INFO logs serve as the basis for:
- **Statistics**: Action distributions, processing volumes, rule effectiveness
- **Health monitoring**: Throughput, error rates, processing latency
- **High-level debugging**: Identify which messages were processed, when, and with what outcome

**Example (email analyzer):**
```
INFO: Asking Gemini (via API) about message abc123 from 2025-01-15 10:30 AM (UTC-06:00)...
INFO: {event: "analysis_complete", msg_id: "abc123", action: "archive", rule: "newsletters"}
```

### PII in Logs

**What counts as PII (for email):**
- **Email address fields** (To/From/CC/BCC/etc.): Automatically considered PII
- **Subject and Body**: Treated as PII because they could contain it
- **Attachments and metadata** (filenames, content): Treated as PII
- **Analysis reason text**: Free-form explanation from LLM may reference email content

**By log level:**
- **DEBUG**: Contains PII by default (full payloads, subjects, senders, API responses, prompts)
- **INFO**: No PII by default; may include PII if explicitly enabled via env vars
- **WARNING, ERROR, CRITICAL**: Must NEVER contain PII

**Enabling PII in INFO logs** (example for email analyzer):
- `INFO_LOG_EMAIL_SUBJECT=true` - Adds subject to INFO logs (may contain PII)
- `INFO_LOG_EMAIL_SENDER=true` - Adds sender to INFO logs (contains PII)

The exact env var names and mechanism may vary by component; the pattern is opt-in via env vars.

Control the startup warning level with `EMAIL_PII_LOG_NOTICE=WARNING|INFO|DEBUG|ERROR|NONE`.

### DEBUG Logs

For deeper debugging, use `LOG_LEVEL=DEBUG`. DEBUG logs contain PII by default and are suppressed unless explicitly enabled.

### Structured JSON Logging

For GCP Cloud Logging compatibility, use `log_json()` from `agentic_consult.logging` for logs that need to be queryable/metrics-ready. Raw JSON to stdout is parsed by Cloud Logging as structured data.
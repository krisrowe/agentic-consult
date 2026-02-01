# Contributing to Agentic Consult

Thank you for contributing! This guide covers the development workflow and testing requirements.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/krisrowe/agentic-consult.git
cd agentic-consult

# Build environment (creates .venv, installs deps, runs tests)
make build
```

## Before Every Commit

**CRITICAL**: Always run the precommit checks before committing:

```bash
make precommit
```

This command:
1. **Runs pytest** - All 10 tests must pass
2. **Runs security scanner** - No sensitive data in staged files

**Never skip this step!** It prevents:
- Broken tests from being committed
- Customer data leaks
- Personal information exposure
- API keys/tokens from being committed

## Testing

### Running Tests

```bash
# Run unit tests only (fast)
make test

# Run integration tests (slower, hits real APIs)
make test-integration

# Run all tests (unit + integration)
make test-all

# Or manually with pytest
source .venv/bin/activate
pytest tests/unit

# Verbose output
pytest -v

# Specific test file
pytest tests/unit/test_precommit.py
```

### Test Suite Coverage

See **[TESTING.md](TESTING.md)** for detailed testing strategy (**["Sociable Unit Tests"](https://martinfowler.com/bliki/UnitTest.html)** vs. "External").

**Core Tests (Unit):**
- Schema validation
- Security scanner validation
- Backup workflows (mocked I/O)
- Gitignore behavior

**External Tests:**
- End-to-end backup workflows (hitting Drive)
- Gemini API interactions
- Gmail/Refresh command workflows

### Adding New Tests

1. Add test file to `tests/unit/` or `tests/integration/`
2. Use pytest fixtures and assertions
3. Test with synthetic data only (never real customer names/data)
4. Run `make test` or `make test-integration` to verify
5. Run `make precommit` before committing

### Validating Remote MCP Deployment

After deploying infrastructure changes or updating the API Gateway, you must validate the remote connection to ensure the "Zero-Install" stack is fully operational.

**When to validate:**
- After running `./cloud deploy`.
- After modifying `deploy/terraform/openapi.yaml.tftpl`.
- When troubleshooting 403 Forbidden or 404 Not Found errors in the remote client.

**Validation Commands:**

1.  **Low-level Health & Auth Check:**
    ```bash
    # This verifies URL reachability and API Key validity
    consult remote test
    ```

2.  **End-to-End Tool Invocation:**
    ```bash
    # This verifies the Gemini CLI can successfully call tools through the Gateway
    gemini "Triage my emails"
    ```

3.  **Manual Probe (Debug):**
    ```bash
    # Direct JSON-RPC call to the root endpoint
    curl -v -X POST "https://your-gateway-url/?key=your-api-key" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -d '{"jsonrpc": "2.0", "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "curl", "version": "1.0"}}, "id": 1}'
    ```

## Code Style

- Follow existing patterns in the codebase
- Keep functions focused and documented
- Use type hints where helpful
- Test new scanner rules thoroughly

## Security Scanner

The `consult precommit` scanner detects:
- Customer names, slugs, keywords
- Email addresses
- Google Drive folder IDs
- API keys/tokens
- Local usernames

**Test your scanner changes:**
```bash
# Test on current repo
consult precommit

# Include gitignored files
consult precommit --include-ignored
```

## Design & Architecture

This project is built on a "Cognitive Perception" architecture, prioritizing deep context and reasoning over simple automation.

### 1. Core Principles

#### A. SDK Layering Strategy
Business logic belongs exclusively in the SDK (`agentic_consult/sdk/` or domain modules). The SDK is the stable core; all external interfaces are thin clients.
*   **SDK**: Pure Python functions, dataclasses, and exceptions. No transport-specific logic (Click, FastAPI, etc.). Returns data, not text.
*   **Clients**: The CLI (`agentic_consult/cli/`), MCP Server (`agentic_consult/mcp/`), and other apps are equal consumers of the SDK. They handle transport, formatting, and interaction.

#### B. Context Integrity Mandate
To ensure AI agents consistently adhere to project patterns and respect established investments, all design principles, architectural mandates, and maintainer guidance **MUST** be documented within the core files already tracked as context (as defined in `.gemini/settings.json`):
*   **README.md**: High-level features, usage, and troubleshooting.
*   **CONTRIBUTING.md**: Architectural patterns, development workflows, and mandates.
*   **GEMINI.md**: Agent-specific mission, protocol, and behavioral guidelines.

**Do not** fragment documentation into new top-level files (e.g., `DESIGN.md`) or hidden directories that are not already part of the agent's established context. When using Claude as a coding agent, ensure these files are properly referenced or imported (e.g., using the `@` syntax specified in `CLAUDE.md`).

#### C. Sociable Unit Testing
We prioritize tests that verify full features or SDK transactions end-to-end without network I/O.
*   **Deceptiveness of Mocks**: We avoid mocking internal logic because mocks can pass even when integrations are broken. We only mock at the system edge (Network I/O, Third-Party APIs).
*   **Environment-Based Isolation**: We use env vars (e.g., `CONSULT_CONFIG_DIR`) to redirect paths to OS-managed temporary directories. This allows fast (<10ms) real disk I/O while ensuring zero repo pollution and workstation safety.
*   **Reference**: See [TESTING.md](TESTING.md) for the full philosophy.

#### C. Makefile-First Automation
The `Makefile` is the authoritative interface for all development tasks.
*   **Single Entry Point**: Every task (test, build, scan) is achievable via a single `make` command.
*   **Self-Healing**: Targets automatically detect and repair missing prerequisites (like `.venv`) via the `setup` target. Zero manual setup required.

#### D. Tool Independence
We maintain strict independence from specific auxiliary tools. While we leverage interfaces like `gwsa`, the code and documentation avoid hard dependencies or "proprietary" mentions. The goal is a decoupled architecture.

### 2. System Components

#### A. Data Retrievers (Limbs)
Scripts that synchronize remote data to local JSON caches for systematic preservation and search.
*   **Current State**: `triage_emails` caches emails ad-hoc for session duration.
*   **Planned State**: Standalone sync tools (`consult tasks sync`, `consult email sync`) building a persistent "Super-Context" database.

#### B. Context Ingestion (Memory Maker)
`agentic_consult/context.py` bundles local data into a formatted context for Gemini, enforcing size limits and applying exclusion patterns.

#### C. Reasoning Engine (Brain)
The high-level logic (e.g., `analyze_files` or `customers refresh`) that uses the Hybrid Strategy:
1.  **Collect Context**: Load relevant files.
2.  **Apply Exclusions**: Filter noise (logs, binary).
3.  **Synthesize**: Execute Gemini queries to produce actionable answers.

### 3. Strategies & Standards

#### A. Flash-First Performance
We prioritize **capability over raw speed**. We use **Gemini Flash** by default for summarization (cost-effective, fast) and escalate to **Gemini Pro** only for complex multi-domain reasoning.

#### B. Centralized Path Authority
All filesystem paths must be resolved via centralized internal APIs (e.g., `agentic_consult.paths`) that prioritize env var overrides for test safety.

#### C. Logging & PII
*   **Transaction Logging**: Each item processed gets 1-2 INFO logs (start/outcome).
*   **PII Protection**: DEBUG logs contain PII by default; INFO logs are PII-free unless explicitly enabled via env vars. WARNING/ERROR logs must NEVER contain PII.

#### D. Cloud-Agnostic CLI
CLI commands interact only with settings and HTTP REST APIs. Cloud-specific logic (GCP/Terraform) is isolated to deployment tooling (`./cloud` and `deploy/`).
*   **Zero-Install Deployment**: The `./cloud` entry point is a standalone Python script using only the standard library. It manages the entire deployment lifecycle (init, build, push, terraform apply) **without requiring Python-specific setup (pip, venv)** or a local Docker daemon. It assumes only that the standard system orchestrators (`gcloud`, `terraform`, `python3`) are available in the PATH. This enables a "clone and deploy" workflow for cloud admins.
    *   **Maintainer Mandate**: To preserve this capability, all logic within the `deploy/` directory (and the `./cloud` script) **MUST** remain strictly limited to the Python standard library. Do not add dependencies that require `pip install` or an active virtual environment to this specific path.

#### E. Overridable Resources
Config resources (prompts, docstrings) use `load_updateable()` to check for GCS-deployed overrides before falling back to package defaults, enabling hotfixes without image rebuilds.

### 4. Implementation Details

#### A. Authentication (gwsa)
We use **gwsa** as our Google Workspace auth layer rather than direct ADC. This provides clean multi-profile management (personal vs. work) and proactive health checks. Users must run `gwsa profiles add` before email tools work.

#### B. Customer Cloud Integration
The `customer.yaml` in the customer directory is the source of truth for the `drive_folder_id`. The ID is treated as a cached value, validated against the Drive API at runtime. The `register_customer` tool is idempotent and provides self-healing for missing or misconfigured folder IDs.

#### C. Strict Git Identity Enforcement
We enforce committer identity consistency:
1.  **Local Identity Exists**: All unpushed commits must match the local `user.email`.
2.  **No Local Identity**: Every commit in the entire repository history must match the identity Git will use for the next commit.
This prevents accidental leaks of employer or client emails in public repositories.

### 5. Roadmap

*   **Bill Payment Tracking**: `process_bills` tool to verify recurring payments via Monarch integration.
*   **Session Bootstrap**: `guide_user` tool to suggest daily workflows at session start (integrated via Gemini/Claude hooks).
*   **Persistent Context Cache**: Moving from ad-hoc email caching to a persistent local database for cross-session reasoning.

## Development Workflow

1. **Create feature branch**
   ```bash
   git checkout -b feature/your-feature
   ```

2. **Make changes**
   - Write code
   - Add/update tests
   - Update docs if needed

3. **Test locally**
   ```bash
   make test  # Must pass
   ```

4. **Run precommit**
   ```bash
   make precommit  # Must pass with no findings
   ```

5. **Commit**
   ```bash
   git add .
   git commit -m "Brief description of changes"
   ```

6. **Push and create PR**
   ```bash
   git push origin feature/your-feature
   ```

## Common Issues

**Tests failing:**
- Check virtual environment is activated
- Rebuild: `make clean && make build`
- Check for import errors

**Precommit scanner finding false positives:**
- Add patterns to `.gitignore` if appropriate
- Use synthetic test data (e.g., "FakeCorp", "TestCompany")
- Never use real customer names in tests

**Module not found errors:**
- Reinstall in dev mode: `pip install -e '.[dev]'`
- Or use: `make build`

## Questions?

Open an issue or contact the repository owner.

---

# Architecture & Design Philosophy

This project captures the foundational theory, architectural patterns, and strategic trade-offs chosen for the `agentic-consult` toolkit.

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

## 5. Specialized Pattern: The "Cognitive Tool"

Instead of the primary agent managing low-level filters (dates, tags, status), it delegates natural language intent to a specialized MCP tool.

- **Encapsulation**: The sub-agent (MCP tool) understands the domain deeply (e.g. TickTick or Gmail). The primary agent remains a generalist.
- **Context Isolation**: Massive datasets (50k+ tokens) are processed within the tool's execution scope. The primary agent only receives a synthesized answer, preserving its context window for the active conversation.
- **Optimization via Context Caching**:
    - **Strategy**: Use Google Gemini Context Caching for the bulk of the history.
    - **Hybrid Delta Handling**: Since caches are immutable, use a "Cold Cache" for historical data and a "Hot Delta" (appended to the prompt) for items modified since the cache was created.
    - **Efficiency**: Reduces latency and token costs by avoiding full re-uploads of history on every change.

## 6. Framework Selection: Custom Orchestration vs. LangGraph/Frameworks

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

## 8. MCP Tool Design & UX Guidelines

When implementing features or changes that involve a specific user experience (UX) at the agent touchpoint:

1. **Lean on Tool Docstrings:** Use the tool's docstring to provide instructions to the agent on how to interpret, format, and present the tool's output to the user. This ensures consistent behavior across different client agents.
2. **Minimal Schema Expansion:** Expand the tool's response JSON schema only when necessary for structural clarity. If the guidance can be handled via the docstring or a specific instruction within the response (like an `instructions` field), prefer that over complex schema changes.
3. **Task-Specific Commands:** Design the agent's interaction to suggest and handle concise "DSL" style commands (e.g., `do accept A1`) for common multi-step operations.
4. **Agent Flexibility:** Allow the MCP client agent to adapt to circumstances with creative problem solving. Do not be overly prescriptive in how it must work with the end user in presenting and acting upon responses. The goal is to orchestrate workflows, not to rigidly script every interaction.
5. **Runtime Schema Validation:** Ensure that defined JSON schemas (`schemas/*.json`) are actively used at runtime to validate data entering or leaving the system. This prevents "interface drift" where code and documentation diverge.

---

# Detailed Testing Strategy

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
*   **Execution**: Fast, deterministic, run by default.
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

### Integration Prerequisites
Running integration tests (`tests/integration/`) requires:
1.  **Authentication**: You must be authenticated with Google Drive via Application Default Credentials (ADC).
    *   Run `gcloud auth application-default login` OR set `GOOGLE_APPLICATION_CREDENTIALS`.
    *   The tests need permission to read/write/create files and folders on Drive.
2.  **Artifacts**: These tests **WILL** create temporary folders and files on your Google Drive (e.g., `Consult_Test_Backup_...`).
    *   Tests attempt to clean up, but failures may leave artifacts behind. You may need to manually prune them occasionally.

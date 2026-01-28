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

#### B. Sociable Unit Testing
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
*   **Zero-Install Deployment**: The `./cloud` entry point is a standalone Python script using only the standard library. It manages the entire deployment lifecycle (init, build, push, terraform apply) without requiring `pip`, `venv`, or any installed dependencies on the deployer's machine. This enables a "clone and deploy" workflow for cloud admins.

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

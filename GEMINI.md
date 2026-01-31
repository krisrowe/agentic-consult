# AI Agent Guide - Agentic Consult

## Design Governance & Architectural Integrity
**CRITICAL:** Before proposing or implementing refactoring, new features, or architectural changes, you **MUST** review **[DESIGN.md](DESIGN.md)**.
*   **Authority:** `DESIGN.md` is the source of truth for the system's blueprints, schemas, and data flows.
*   **Compliance:** Do not deviate from the patterns defined therein without explicit user approval.
*   **Evolution:** If a change is needed that contradicts `DESIGN.md`, you must propose updating the design document first.

## Mission: The Executive Assistant

**"I want this thing to be an executive assistant that knows everything that everyone wants from me and can help propose priorities but ultimately works with me and under me but helps me not forget or lose track of things nor spend many brain cycles on cross referencing and all that and gets me to decision making and action as quickly and efficiently as possible with the right information at the right times."**

This repository provides the "Super-Senses" and "Cognitive Tools" required to fulfill this mission. Your role is to orchestrate these tools to reduce cognitive load and accelerate decision-making for the user.

---

This guide is for AI agents (like Gemini CLI with MCP) that help users work **with** or **on** this repository.

## Two Use Cases

**1. Contributing to this Repository (Developer/Contributor Context)**
- Working ON the agentic-consult codebase itself
- See the "Contributing" section below for specific guidance

**2. Using the `consult` CLI Tool (User Context)**  
- Using the tool from other repositories for customer workflows
- See the rest of this guide for usage patterns

## Repository Documentation

For a deeper understanding of the project's direction and technical implementation, refer to:

- **[ARCHITECTURE.md](ARCHITECTURE.md)**: The "Why." Captures the foundational theory (Cognitive Perception Architecture), the Hub-and-Spoke pattern, and strategic trade-offs (e.g., Context Caching vs. Vector RAG).
- **[DESIGN.md](DESIGN.md)**: The "How." Concrete implementation blueprints, component details, JSON schemas, and the step-by-step transition plan for the codebase.

**Usage Note:**
*   **Periodic Review:** Agents and contributors should review `DESIGN.md` periodically during active development to ensure alignment with the latest patterns (e.g., Customer Cloud Integration).
*   **Deviation Protocol:** If you find a need to deviate from `DESIGN.md`, do not proceed silently. Discuss the rationale with the user and obtain approval to either (a) deviate as a documented exception or (b) update `DESIGN.md` to reflect the new direction.

---

## Agent Workflow Overview

You will help users by invoking the `consult` CLI to:
1. Manage customer configurations
2. Scan emails and create tasks
3. Generate and organize issue tracking notes
4. Perform security scans before commits
5. Create backups

## Core CLI Commands

### Customer Management

**Initialize new customer:**
```bash
consult customers init --slug <slug> --name "<Name>"
```
- Creates customer config at `~/.config/agentic-consult/customers/<slug>/`
- Auto-discovers or creates Google Drive folder (requires gwsa)

**Show customer info:**
```bash
consult customers show <slug>
```

**Add customer notes:**
```bash
consult customers notes add <slug> --content "..."
consult customers notes add <slug> --file /path/to/file.md
```

### Email Scan & Task Creation

**Refresh workflow** (scan emails, create tasks, update issues):
```bash
# Preview what would be done (safe, dry-run)
consult customers refresh <slug> --dry-run

# Execute (requires gwsa + TickTick access)
consult customers refresh <slug> --no-dry-run
```

**Expected behavior:**
- Searches Gmail for unreplied messages from customer
- Creates TickTick tasks for new emails
- Matches emails to existing issue files or creates new ones
- Saves attachments to customer's directory

### Security Scanning

**Before any git commit, always run:**
```bash
consult precommit
```

This scans for:
- Customer names, slugs, keywords
- Email addresses
- Drive IDs
- API keys/tokens
- Local usernames

**Include gitignored files in scan:**
```bash
consult precommit --include-ignored
```

### Backup operations

**Backup customer data to Drive:**
```bash
consult backup all
```

## MCP Tool Design & UX

When implementing features or changes that involve a specific user experience (UX) at the agent touchpoint (e.g., Gemini CLI, Claude Code):

1. **Lean on Tool Docstrings:** Use the tool's docstring to provide instructions to the agent on how to interpret, format, and present the tool's output to the user. This ensures consistent behavior across different client agents.
2. **Minimal Schema Expansion:** Expand the tool's response JSON schema only when necessary for structural clarity. If the guidance can be handled via the docstring or a specific instruction within the response (like an `instructions` field), prefer that over complex schema changes.
3. **Task-Specific Commands:** Design the agent's interaction to suggest and handle concise "DSL" style commands (e.g., `do accept A1`) for common multi-step operations.
4. **Agent Flexibility:** Allow the MCP client agent to adapt to circumstances with creative problem solving. Do not be overly prescriptive in how it must work with the end user in presenting and acting upon responses. The goal is to orchestrate workflows, not to rigidly script every interaction.
5. **Runtime Schema Validation:** Ensure that defined JSON schemas (`schemas/*.json`) are actively used at runtime to validate data entering or leaving the system. This prevents "interface drift" where code and documentation diverge.

## Context-Aware Gemini Query

**Query Gemini with file context:**
```bash
consult gemini "Prompt..." [PATH]... [--exclude PATTERN]
```
- Supports files and directories as context paths.
- Uses `.gitignore`-style exclusion patterns.
- Automatically skips binary files.

## Strategic Principles

1. **Tool Independence:** Maintain strict independence from specific auxiliary tools or repositories. While current implementations may leverage certain interfaces (like `gwsa`), the code, configuration, commit messages, and documentation should avoid hard dependencies or specific mentions of auxiliary projects as "personal" or "proprietary." The long-term goal is a fully decoupled architecture that relies solely on generic capability requirements.

## Integration with MCP/gwsa

The tool expects these MCP capabilities:

**Gmail (via gwsa):**
- `gwsa gmail search "in:inbox from:<customer>"`
- `gwsa gmail get <message-id>`

**Drive (via gwsa):**
- `gwsa drive ls <folder-id>`
- `gwsa drive mkdir --parent <id> --name "<name>"`
- `gwsa drive upload --file <path> --parent <id>`

**TickTick:**
- Create tasks via TickTick API/MCP

### TickTick Integration

The `refresh` command requires a `TICKTICK_ACCESS_TOKEN` environment variable to fetch tasks.

> [!TIP]
> If the TickTick MCP server has been set up on the workstation, you may find the token in `~/.gemini/settings.json` under the `ticktick` MCP server configuration. You can use this token for local CLI operations, but **never** include the token value in any versioned files or commit messages.

## Customer Data Structure

**Customer config location:**
```
~/.config/agentic-consult/customers/<slug>/
├── customer.yaml       # name, slug, drive_folder_id, keywords
├── notes/             # Customer notes
└── issues/            # Email-generated issue tracking (optional)
```

**customer.yaml schema:**
```yaml
name: "Customer Name"
# The slug should typically be the customer's email domain without the suffix
# (e.g., "acme" for "acme.com"). If the slug differs from the email domain,
# add the domain name (without suffix) to keywords to help detect customer data.
slug: customer-slug
drive_folder_id: "DriveID123456"
keywords:
  - keyword1
  - keyword2
```

## Agent Best Practices

### When to use dry-run
- **Always start with `--dry-run`** for refresh commands
- Show user the preview
- Ask for confirmation before running with `--no-dry-run`

### Local vs XDG storage
- Customer data lives in `~/.config/agentic-consult/` (XDG)
- The git repository at `~/ws/consult/` (or wherever) contains only code
- **Never** commit customer data to git
- Use `.gitignore` to exclude `customers/`, `customer.yaml`, `issues/`

### Dependency Management
- **Always use `pipx`** to install Python tools locally (e.g., `ticktick-access`, `gwsa`).
- `pipx` ensures tools are isolated and don't conflict with system packages or other projects.
- Example: `pipx install -e ./path/to/local/tool`

### Security workflow
1. Before committing code changes: `consult precommit`
2. If scan fails, review findings with user
3. Either fix issues or update `.gitignore`
4. Re-run scan until clean
5. **CRITICAL**: Review commit message for sensitive data
   - **NEVER include customer names, slugs, keywords, email addresses, or any sensitive data that the scanner detects in git commit messages**
   - The scanner only checks file contents, not git metadata
   - Use generic examples (e.g., "customer", "example-corp") instead of real customer data
6. Then `git commit`

### Issue tracking workflow
1. User receives email from customer
2. Run refresh to scan emails: `consult customers refresh <slug> --dry-run`
3. Review plan with user
4. Execute: `--no-dry-run`
5. Check created TickTick tasks and issue files

 ### Backup workflow
 1. Periodic backups: `consult backup all`
 2. Uploads customer data to their configured Drive folder
 
 ## Configuration Management
**View config:**
```bash
consult config show
```

**Set custom customer data path:**
```bash
consult config set customers-local-path /custom/path
```

**Set Drive parent folder for all customers:**
```bash
consult config set customers-cloud-folder-id <drive-folder-id>
```

## Error Handling

**Common issues:**

1. **"Customer not found"** - Run `customers init` first
2. **"gwsa not found"** - Install google-workspace-access MCP tool
3. **"Drive folder not found"** - Check `drive_folder_id` in customer.yaml
4. **Precommit fails** - Review scanner output, check if sensitive data should be gitignored

## Privacy & Security

**Critical rules:**
- Customer names/slugs/keywords are kept in XDG config directory
- **Never** commit customer.yaml to git
- **Always** run precommit before git commits
- Customer data directories are gitignored by default
- Sensitive information detection is automatic

**Gitignored by default:**
```
customer.yaml
customers/
issues/
.venv/
*.egg-info/
.pytest_cache/
*.log
```

## Cloud Deployment & MCP

This repository includes a "Zero-Install" cloud deployment system to run the MCP server on Google Cloud (Cloud Run).

**Architecture:**
- **Private Cloud Run:** Hosts the MCP server.
- **Public API Gateway:** Proxies requests, secured by an **API Key**.
- **Cloud Scheduler:** Triggers background jobs (email fetching/analysis).

**Agent Workflow:**

1.  **Initialize (Admin):**
    ```bash
    ./cloud init --project=my-project-id
    ```
    *   This sets up the `terraform-deployer` Service Account and required Org Policies.
    *   It saves the SA key to `~/.config/agentic-consult/cloud-deploy-svc-account.json`.

2.  **Deploy (Admin):**
    ```bash
    ./cloud deploy
    ```
    *   Automatically transfers images from GHCR to GCR using Cloud Build.
    *   Runs Terraform to provision infrastructure.
    *   This command is idempotent and safe to re-run.

3.  **Connect (User):**
    ```bash
    ./cloud user-auth export > creds.yaml
    cat creds.yaml | consult remote auth import
    consult remote register
    ```
    *   This outputs the `gemini mcp add` command with the correct Gateway URL and API Key.

**Key Concepts:**
*   **No Local Docker:** All builds happen in the cloud.
*   **Single Identity:** Deployment uses a dedicated Service Account.
*   **Simple Auth:** Clients connect via `https://gateway-url/sse?key=API_KEY`. No complex tokens required for user endpoints.

## Example Agent Session

```
User: "Set up tracking for Acme Corp"

Agent: I'll initialize a customer configuration for Acme Corp.

[Run] consult customers init --slug acme --name "Acme Corp"
[Output] Created customer config. Drive folder: 1abc...xyz

Agent: Customer "Acme Corp" is now configured. The Drive folder was auto-created
       at ~/.config/agentic-consult/customers/acme/

User: "Check for new emails and create tasks"

Agent: I'll preview what would be done:

[Run] consult customers refresh acme --dry-run
[Output] Would create 3 tasks, update 2 issues, save 1 attachment

Agent: This would create 3 TickTick tasks for unreplied emails. Proceed?

User: "Yes"

[Run] consult customers refresh acme --no-dry-run
[Output] Created 3 tasks, updated 2 issue files

Agent: Done. Created 3 TickTick tasks and updated issue tracking files.
```

## Development Workflow

When helping users work on the codebase itself:

**Critical: Always run before committing:**
```bash
make precommit  # Runs pytest (10 tests) + security scanner
```

**Individual development commands:**
```bash
# Install for development
make build

# Run tests only (pytest)
make test

# Run security scan only
consult precommit

# Clean build artifacts
make clean
```

**Test coverage:**
- See **[TESTING.md](TESTING.md)** for the project's testing philosophy (**["Sociable Unit Tests"](https://martinfowler.com/bliki/UnitTest.html)**).
- **Philosophy**: Avoid "Solitary" tests. Test full workflows from the SDK/CLI entry point. Use real file system operations (temp dirs) over mocking, unless strictly network-bound.
- **Core Tests (`tests/unit/`)**: Run by default. Verify full features without network I/O.
- **External Tests (`tests/integration/`)**: Verify real API interactions (Drive, Gmail).

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed contributor guidelines.

## Summary

As an AI agent, your role is to:
1. **Invoke CLI commands** based on user intent
2. **Start with dry-runs** for safety
3. **Always scan before commits** using precommit
4. **Keep customer data separate** from code repository
5. **Explain what commands do** before running them

The `consult` CLI handles the actual work - you orchestrate it based on user needs.
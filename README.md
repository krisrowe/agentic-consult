# Agentic Consult

A Python CLI tool (and soon-to-be MCP server) designed for use with terminal-based AI agents (tested with Gemini CLI) to manage customer consulting workflows, email and instant message tracking, task tracking, and related automation. Features Google Workspace integration (Gmail, Google Drive, Chat to come) with built-in security scanning to protect customer data.

## Overview

This tool helps automate customer support workflows by:
- Managing customer configurations (stored in XDG-compliant directories)
- Scanning files for sensitive data before commits
- Providing CLI commands for customer management, backups, and workflows
- Integrating with Gmail (via [gwsa](https://github.com/krisrowe/gworkspace-access)/MCP) and TickTick for task management

**Privacy First**: Customer data is kept in local XDG directories (`~/.config/agentic-consult/customers/`) and never committed to git.

> [!IMPORTANT]
> **Critical for Agent-Assisted Workflows**: In the early age of agentic coding and workflow management, AI coding assistants that help consultants with both customer projects and their own tooling can inadvertently inject customer examples into generated code, configuration files, documentation, and code comments. As agents encounter real customer data in your workspace (emails, notes, configurations), they may reference this information when generating or refactoring code. **This scanner addresses this pressing risk** by detecting sensitive data before commits, making it essential for engineers using AI-assisted development workflows.

> [!TIP]
> **Standalone Security Scanner**: The built-in `consult precommit` scanner can be used independently of the customer management and workflow automation features. Install this tool in any development environment to scan repositories for sensitive data (customer names, emails, API keys, etc.) before committing or sharing code publicly. No Google Workspace integration or customer configuration required for scanner-only usage.

**AI Agent Integration**: This tool is designed to work with AI assistants like Gemini CLI. See [GEMINI.md](GEMINI.md) for the agent-facing guide.

## Features

*   **Customer Management**: Initialize, configure, and manage customer profiles.
*   **Context Refresh**: Fetches emails, matches them to tasks/issues, and prepares a daily briefing.
*   **Security Scanner**: Pre-commit hook to prevent leaking sensitive data (secrets, customer names).
*   **Backups**: Automated backups of local repositories to Google Drive.
*   **Task Integration**: Syncs with TickTick for task management.
*   **Gemini Command**: Direct interface to Gemini API with context-aware file processing.
*   **MCP Server**: Exposes tools (Backup, Scan, Analyze Files) to Gemini CLI. See [MCP-SERVER.md](MCP-SERVER.md).

## MCP Server & Tools

This repository exposes its capabilities via the Model Context Protocol (MCP), allowing AI assistants (like Gemini CLI or Claude Desktop) to use them as tools.

### Why use `analyze_files`?

The `analyze_files` tool allows an agent to request analysis of local files by delegating the reading and processing to a sub-call. While it might seem counterintuitive for a local agent to call a tool just to read files, this approach offers critical advantages:

1.  **Context Hygiene**: You avoid polluting your main agent session's context with the raw content of massive file trees. If you read everything into the main session, that data is re-sent with *every* subsequent request, degrading performance, increasing cost, and racing toward context limits.
2.  **Isolation**: You can ask a targeted question ("Check these logs for errors") in an isolated context. The main agent receives only the answer, not the noise.
3.  **Precision**: It provides a standard, predictable syntax (using `.gitignore` style patterns) to control exactly which files are considered, ensuring the model focuses only on relevant data.

For installation, configuration, and a full list of tools, see below.

### Available Tools

The MCP server exposes a comprehensive toolkit for consulting and development workflows.

#### 📁 Backup & Metadata
| Tool | Description |
|------|-------------|
| `assess_workstation_backup_state` | Dry-run assessment of all configured backup providers. |
| `backup_local_repo` | Backup a single git repository to Google Drive. |
| `check_repo_status` | Detailed backup and sync status for a specific repository. |
| `get_backup_metadata` | Retrieve description and keywords for a repository. |
| `set_backup_metadata` | Set description/keywords in local git config. |
| `generate_backup_metadata` | Propose metadata using Gemini analysis of the repo. |
| `clear_backup_metadata` | Remove backup metadata from local config. |

#### 📧 Email Triage & Analysis
| Tool | Description |
|------|-------------|
| `triage_emails` | **Primary Entrypoint.** Fetch and analyze unread emails for triage. |
| `get_cached_emails` | Retrieve full content for emails analyzed in the current session. |
| `archive_email` | Archive an email and log the action for rule efficiency. |
| `mark_email_in_review` | Apply/remove the 'Reviewing' label. |
| `analyze_emails` | On-demand Gemini analysis for specific message IDs. |
| `reset_analysis` | Force re-analysis of all emails for a specific date. |
| `flag_for_reanalysis` | Flag specific emails to be re-processed by the background analyzer. |
| `email_triage_stats` | Triage health metrics and rule effectiveness report. |

#### ⚙️ Configuration & Rules
| Tool | Description |
|------|-------------|
| `list_email_rules` | List active processing rules with usage statistics. |
| `add_email_rule` | Add a new auto-archive or review rule. |
| `remove_email_rule` | Delete an email processing rule. |
| `configure_email_rules` | Batch update rules (add, update, delete, enable/disable). |
| `configure_triage_batching` | Adjust fetch pool and presentation batch sizes. |

#### 🧠 Analysis & Context
| Tool | Description |
|------|-------------|
| `analyze_files` | Reason about local files with recursive context and exclusions. |
| `analyze_context` | Query the `GEMINI.md` context file directly. |
| `workspace_status` | Multi-repo health check (identity, sync state, dirtiness). |

#### 👥 Customer & Chat
| Tool | Description |
|------|-------------|
| `list_customers` | List all registered consulting customers. |
| `get_customer_info` | Detailed local and cloud status for a customer. |
| `register_customer` | Initialize a new customer configuration (local + Drive). |
| `get_chat_mentions` | Scan Google Chat for actionable mentions and unread DMs. |
| `get_recent_group_chats` | List recent active spaces and group DMs. |

#### 🛡️ Security & Privacy
| Tool | Description |
|------|-------------|
| `run_precommit_scan` | Comprehensive PII and secret detection for code repos. |
| `get_fake_email_addresses` | Whitelisted placeholder emails for safe documentation/tests. |

### Usage Examples

**Gemini CLI:**

```bash
# Backup the current repo
gemini "backup this repo"

# Run a security scan
gemini "scan this directory for secrets"

# Analyze documentation
gemini "Summarize the architecture from docs/"
```

### Registration (Local)

To run the MCP server locally (stdio transport):

```bash
gemini mcp add consult consult-mcp --stdio --scope user
```

For Cloud MCP (HTTP transport), see the [Cloud Deployment](#cloud-deployment) section.

### AI Agent Integration

#### VS Code (Gemini Code Assist)
Gemini Code Assist in VS Code uses the same user-level configuration as the Gemini CLI. Once you have registered the server locally with the `--scope user` flag, it will be **automatically available** in VS Code. Use the `@consult` handle in the VS Code sidebar to direct requests to these tools.

#### Claude Code CLI
For Claude Code, use the `-e` flag to pass the required `GEMINI_API_KEY`:

```bash
claude mcp add --scope user consult -e 'GEMINI_API_KEY=${GEMINI_API_KEY}' -- consult-mcp
```

### Troubleshooting (Local MCP)

- **"Command not found: consult-mcp"**: Ensure you have installed the package (`pipx install .`) and your virtual environment is active or the script is in your PATH.
- **"Server not found: consult"**: Run `gemini mcp list` to check if the server is registered. If missing, repeat the `gemini mcp add` step.
- **Backup Errors**: Ensure you have run `consult backup config` to set the destination Drive folder.

## Installation

The recommended way to install `agentic-consult` is via `pipx` to ensure isolation and global availability.

```bash
# Install from source
pipx install .

# If you encounter import errors, try forcing a reinstall
pipx install . --force
```

## Prerequisites

- **Python 3.10+** (Modern type hinting support)
- **Git 2.11+** (Required for `consult repo-status` and backups; uses `--porcelain=v2` status format)
- [Google Workspace Access (gwsa)](https://github.com/krisrowe/gworkspace-access) - Python dependency for email tools (installed automatically). **Requires auth setup via `gwsa profiles add`** before use.
- [TickTick Access](https://github.com/krisrowe/ticktick-access) - For task management.

## Agent Capability Requirements

When using `agentic-consult` via an MCP-compatible AI agent (e.g., Gemini CLI, Claude Code), the agent's environment is expected to provide certain baseline capabilities as tools to orchestrate full workflows:

- **Email Management:** Ability to search, read, and modify emails (labels/archiving) to support triage workflows.
- **Calendar Orchestration:** Ability to list, create, and respond to calendar events to facilitate automated scheduling and availability checks during triage.
- **Drive/File Management:** Ability to manage cloud-based files and folders for automated backups and document organization.
- **Task Management:** Ability to create and update tasks in external systems (like TickTick) based on workflow outcomes.

The tool logic is designed to be **provider-agnostic**; as long as the agent has tools capable of fulfilling these high-level functions, the specific tool implementation (e.g., Google's MCP extension vs. custom `gwsa` tools) is transparent to the workflow.

## Authentication & Setup

This tool requires authentication for three distinct services:

1.  **Gmail Integration**: Requires `gwsa` CLI installed and authenticated.
    ```bash
    pipx install google-workspace-access
    gwsa auth login
    ```

2.  **Google Drive (Backups)**: Uses Application Default Credentials (ADC).
    - **Standard**: Run `gcloud auth application-default login`.
    - **Custom**: Set `GOOGLE_APPLICATION_CREDENTIALS` environment variable to the path of a valid Service Account key or Authorized User credentials JSON file.
    - **Client ID Restrictions**: Some accounts (e.g., personal `gmail.com` or restricted Workspace orgs) block the default `gcloud` client from accessing sensitive scopes like Drive. In this case, `gcloud auth application-default login` will fail or yield insufficient permissions. You must bring your own OAuth Client ID, generate credentials via a custom script (e.g., using `google_auth_oauthlib`), and point `GOOGLE_APPLICATION_CREDENTIALS` to the resulting JSON file.

3.  **Gemini API**: Requires an API Key.
    ```bash
    export GEMINI_API_KEY="your-key-here"
    ```

## Debugging

Set `CONSULT_DEBUG_GEMINI_MCP=true` in your environment to include `--debug` flag when invoking Gemini CLI. This can help verify that MCP servers are correctly disabled.

```bash
export CONSULT_DEBUG_GEMINI_MCP=true
consult customers refresh <slug> --dry-run
```

## Quick Start

1. **Initialize a customer:**
```bash
consult customers init --slug acme --name "Acme Corp"
```

2. **Run precommit scan:**
```bash
consult precommit
```

3. **Run tests:**
```bash
make test
```

4. **Cloud deployment** (optional) - see [Cloud Deployment](#cloud-deployment) section below.

## Key Commands

Explore all available commands and options by running `consult --help`.

### Customer Management
```bash
# List/show customer
consult customers show <slug>

# Add note
consult customers notes add <slug> --content "Meeting notes..."

# Backup customer data
consult backup all

# Query Gemini with context
consult gemini "Summarize these files" src/ docs/ --exclude "*.test.py"
```

### Security Scanning
```bash
# Scan current directory (staged files + local files)
consult precommit

# Scan a specific repository
consult precommit /path/to/any/repo

# Include gitignored files
consult precommit --include-ignored
```

**Note**: The `consult precommit` command runs ONLY the security scanner (no tests). Use `make precommit` when contributing to this repository to run both tests and scanner.

### Backups
The `consult backup all` command safeguards your work by backing up repositories to Google Drive.

```bash
# Run backup for all configured locations
consult backup all

# Dry-run to preview actions
consult backup all --dry-run
```

**Discovery Logic:**
- **Recursive Search**: The tool searches recursively starting from the configured `backups.local_repos.path`.
- **Nested Repositories**: It detects repositories nested inside other folders or even inside other repositories (e.g., submodules or vendored code).
- **Depth**: It traverses as deep as the file system allows, skipping only `.git` directories themselves.

**Configuration Requirement:**
To use the backup feature, you **MUST** configure the root directory for repository discovery. There is **no default** path (e.g., we do not default to `$HOME` as scanning the entire home directory would be extremely slow and resource-intensive).

```bash
# Configure the root search path for local repos
consult config set backups.local_repos.path /home/user/workspace
```

### Configuration
```bash
# Show config
consult config show

# Set config value
consult config set customers-local-path /path/to/customers

### TickTick Integration (Optional)

The `refresh` command integrates with TickTick to fetch and manage tasks.

1.  **Install `ticktick-access`**: Ensure the `ticktick` CLI is installed and available in your PATH.
2.  **Configure Client**: Run `ticktick client set` to provide your TickTick OAuth client ID and secret.
3.  **Authenticate**: Run `ticktick auth` to authorize the tool and obtain an access token.
4.  **Verify**: Run `ticktick status` to ensure you are authenticated.

The `consult` tool will automatically discover the access token from the `ticktick-access` configuration or the Gemini MCP settings. Alternatively, you can set the `TICKTICK_ACCESS_TOKEN` environment variable.

## Project Structure

```
agentic_consult/          # Main Python package
  cli.py                  # CLI commands
  scanner.py              # Security scanner
  customers.py            # Customer management
  config.py               # Configuration
  ...
tests/                    # Test suite
  unit/                   # Unit tests
  schemas/                # JSON schemas
setup.py                  # Package config
Makefile                  # Build targets
```

## Configuration & Data Storage

The tool separates **global configuration** from **user data** (customers, tasks, etc.), adhering to XDG standards by default but allowing for overrides.

### Global Settings
Stored in `~/.config/agentic-consult/settings.json`. This file controls how the tool behaves and where it looks for data.

**Key Setting:** `local_data`
- Defines the root directory for all user data.
- **Default:** `~/.local/share/agentic-consult/` (Linux/Mac)
- **Override:** Set this to any path (e.g., a private git repo) to store your customer data there.

### Data Structure
Whether using the default or a custom `local_data` path, the structure remains the same:

```text
[local_data]/
├── customers/
│   ├── acme/
│   │   ├── customer.yaml  <-- Customer-specific config
│   │   └── ...
│   └── ...
└── ...
```

### CLI Management
Use the CLI to manage these settings without editing files manually.

```bash
# Show current configuration and resolved data paths
consult config show

# Change the storage location (e.g., to a private configuration repo)
consult config set local_data /home/user/private-config-repo/agentic-consult/data
```

## Cloud Deployment

Deploy the email triage system to Google Cloud for automated background processing. This project uses a "Zero-Install" deployment system that runs entirely from the repository using `python3` and `gcloud`, with no local Docker required.

### Architecture

The system uses a **Private Cloud Run** backend fronted by a **Public API Gateway** for secure, serverless operation.

```
  INTERNET                                  GCP PROJECT (Private Network)
┌──────────┐                            ┌──────────────────────────────┐
│  Client  │  https://gateway/sse?key=X │                              │
│ (Claude/ │ ──────────────────────────►│        API Gateway           │
│  Gemini) │                            │      (Public Facade)         │
└──────────┘                            └──────────────┬───────────────┘
                                                       │
                                                       │ (OIDC Auth)
                                                       ▼
┌──────────┐                            ┌──────────────────────────────┐
│  Cloud   │                            │         consult-mcp          │
│ Scheduler│ ──────────────────────────►│     (Cloud Run Service)      │
│          │        (OIDC Auth)         │          [PRIVATE]           │
└──────────┘                            └──────────────────────────────┘
```

**Security Model:**
1.  **Public Access (API Gateway):** Secured by an **API Key**. Only clients with the key can pass the gateway. Exposes `/sse` and `/messages` endpoints.
2.  **Service Access (Cloud Run):** Secured by **IAM**. Only the API Gateway and Cloud Scheduler Service Accounts have `roles/run.invoker`. Direct internet access is blocked.
3.  **Deployment:** Managed by a dedicated `terraform-deployer` Service Account with `roles/owner`, bypassing local user permission issues.

### Prerequisites

**GCP Setup:**
- A GCP project with billing enabled
- `gcloud` CLI installed and authenticated (`gcloud auth login`)
- User must be **Owner** (to set org policies and create service accounts during init)

### Step-by-Step Deployment

**1. Initialize cloud environment:**

```bash
# First time setup (interactive)
./cloud init --project=my-project-id
```

`init` will:
- Enable required APIs and Org Policy overrides (e.g., enabling public access for Gateway)
- Create the `terraform-deployer` Service Account and key
- Validate or prompt for required secrets (`gemini-api-key`, `gmail-token`)
- Create the storage bucket
- Save the deployment key to `~/.config/agentic-consult/cloud-deploy-svc-account.json`

**2. Deploy Infrastructure:**

```bash
./cloud deploy
```

This automated command:
- **Checks Images:** Verifies if images exist in GCR/Artifact Registry.
- **Transfers Images:** If missing, triggers **Cloud Build** to transfer the MCP image from GHCR to GCR.
- **Builds Images:** Triggers **Cloud Build** to build the Fetcher image from source (if needed).
- **Runs Terraform:** Provisions API Gateway, Cloud Run, and Scheduler using the specific git SHA as the image tag.

**3. Connect Client:**

```bash
# Export connection info
./cloud user-auth export > creds.yaml

# Import to local CLI
cat creds.yaml | consult remote auth import

# Register with AI Agent
consult remote register
```

### Management Commands

| Command | Description |
|---------|-------------|
| `./cloud status` | Check health of project, secrets, and images. |
| `./cloud scheduler list` | View active background jobs. |
| `./cloud user-auth export` | Get client connection info (Gateway URL + API Key). |
| `./cloud deploy --ref <SHA>` | Deploy a specific git commit. |
| `./cloud deploy config` | Sync config files (prompts) to GCS without image rebuild. |

### Internals

**Zero Local Docker:**
The deployment script serves as a bridge. You never run `docker build` locally.
- **Internal Components (MCP):** Built by GitHub Actions -> GHCR. Script moves them to GCR via Cloud Build.
- **External Components (Fetcher):** Built by Cloud Build directly from source.

**Idempotency:**
The script is designed to be run repeatedly. It checks existence before creating/transferring, ensuring fast deploys when images are already present.

## Development

**Before any commit, always run:**
```bash
make precommit  # Runs pytest + security scanner
```

This target:
1. Runs the full test suite (10 tests via pytest)
2. Scans all files for sensitive data

**Individual commands:**
```bash
# Run tests only
make test

# Run security scan only
consult precommit

# Build clean environment
make build

# Clean artifacts
make clean
```

**For contributors**: See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed development workflow.

## Security

The built-in `precommit` scanner detects:
- Customer names, slugs, keywords
- Email addresses
- Drive folder IDs  
- API tokens/keys
- Local usernames

**Always run `make precommit` before committing!**

## Documentation

- See `GEMINI.md` for AI agent integration guide
- Customer data is gitignored by default
- Sensitive data stays in XDG directories, never in the repo

## License

Internal tool - consult repository owner for usage.

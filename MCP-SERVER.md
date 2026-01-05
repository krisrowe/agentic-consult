# Agentic Consult MCP Server (`consult-mcp`)

A **Model Context Protocol (MCP)** server that exposes the `agentic-consult` tools to AI assistants like Gemini CLI and Gemini Code Assist (VS Code).

## What is MCP?

The [Model Context Protocol](https://modelcontextprotocol.io/) enables AI assistants to securely connect to external tools. This server exposes:

- **Backup Tools**: Backup local git repositories to Google Drive.
- **Security Tools**: Scan local directories for sensitive data (secrets, customer names) before committing.
- **Analysis Tools**: Reason about local project files and documentation.

## Features

### Tools (Actions)

| Tool | Description |
|------|-------------|
| `analyze_files` | Analyzes local files using Gemini. Recursively gathers context from files/folders with exclusion support. |
| `assess_workstation_backup_state` | Assesses backup state of the entire workstation (all configured providers). |
| `backup_local_repo` | Backs up a single local git repository to Google Drive. |
| `check_repo_status` | Checks the backup status of a git repository (Local-Only or Remote). |
| `run_precommit_scan` | Runs a pre-commit scan for sensitive data in a local directory. |
| `process_email` | Returns email processing workflow instructions with configured rules. |
| `list_email_rules` | Lists all email processing rules with usage statistics. |
| `add_email_rule` | Adds a new email processing rule (auto_archive or custom). |
| `remove_email_rule` | Removes an email processing rule by ID. |
| `auto_archive_email` | Archives an email via gwsa and logs for tracking/recovery. |

### Email Processing Tools

The email tools help automate inbox management with rule-based archiving:

1. **Rules Configuration**: Rules are stored in `~/.config/agentic-consult/email.yaml`. Use `add_email_rule` to create auto-archive or custom rules with time-based conditions.

2. **Archive Tracking**: The `auto_archive_email` tool both archives emails (via gwsa SDK) AND logs each action to a cache file. This enables:
   - **Rule efficiency analysis**: `list_email_rules` shows `use_count` and `last_used` for each rule. Rules with zero usage over months are candidates for removal to reduce agent context overhead.
   - **Forensic recovery**: If emails are incorrectly archived, the log (`$XDG_CACHE_HOME/agentic-consult/email-archive-log.jsonl`) provides a record for review and recovery.

3. **Workflow Instructions**: Call `process_email` to get the full workflow with current rules interpolated.

**Always use `auto_archive_email`** instead of direct gwsa calls when archiving rule-matched emails to ensure proper tracking.

### Configuration Dependency

**Important**: These MCP tools rely on the global configuration managed by the `consult` CLI. Before using backup-related tools (`backup_local_repo`, `check_repo_status`, `assess_workstation_backup_state`), you must ensure the underlying paths and settings are configured.

Specifically, the backup tools require:
1.  **Google Drive Folder**: `consult config set backups.google_drive_folder_id <ID>`
2.  **Local Repos Path**: `consult config set backups.local_repos.path <PATH>`

If these are not set, the MCP tools will return an error instructing you to configure them via the CLI.

## Quick Start

### Prerequisites

1.  **`consult` CLI installed**:
    ```bash
    pipx install .
    ```

2.  **Backup Configuration**:
    ```bash
    # Set the root path where your local repositories are stored
    consult config set backups.local_repos.path /path/to/your/workspace
    
    # Configure the Google Drive destination
    consult backup config
    ```

3.  **MCP Client**: Google Gemini CLI or Gemini Code Assist (VS Code).

### Step 1: Register the Server

This single command registers the `consult-mcp` server globally for your user, making it available in any Gemini session. The server uses **stdio transport**, meaning the client manages its lifecycle automatically.

```bash
gemini mcp add consult consult-mcp --stdio --scope user
```

### Step 2: Verify

Check the status:

```bash
gemini mcp list
```

You should see `consult` listed with a "Connected" status.

## How It Works

When you run a command like `gemini "backup this repo"`, the Gemini client:
1.  Looks up the `consult` server in its configuration.
2.  Executes the registered command: `consult-mcp`.
3.  Communicates over stdin/stdout.
4.  Terminates the process when the interaction is complete.

## VS Code Integration (Gemini Code Assist)

Gemini Code Assist in VS Code uses the same user-level configuration as the Gemini CLI. Once you have registered the server with the `--scope user` flag, it will be **automatically available** in VS Code. Use the `@consult` handle in the VS Code sidebar to direct requests to these tools.

## Claude Code CLI

For Claude Code, use the `-e` flag to pass the required `GEMINI_API_KEY`:

```bash
claude mcp add --scope user consult -e 'GEMINI_API_KEY=${GEMINI_API_KEY}' -- consult-mcp
```

For detailed setup, troubleshooting, and configuration, see **[docs/CLAUDE-CODE.md](./docs/CLAUDE-CODE.md)**.

## Usage Examples

**Gemini CLI:**

```bash
# Backup the current repo
gemini "backup this repo"

# Run a security scan
gemini "scan this directory for secrets"

# Analyze documentation
gemini "Summarize the architecture from docs/"
```

## Transport Options

| Transport | Description | Use Case |
|-----------|-------------|----------|
| **Stdio** | Server starts/stops with each client session | Recommended for Gemini CLI and local agents. |

## Troubleshooting

- **"Command not found: consult-mcp"**: Ensure you have installed the package (`pipx install .`) and your virtual environment is active or the script is in your PATH.
- **"Server not found: consult"**: Run `gemini mcp list` to check if the server is registered. If missing, repeat the `gemini mcp add` step.
- **Backup Errors**: Ensure you have run `consult backup config` to set the destination Drive folder.
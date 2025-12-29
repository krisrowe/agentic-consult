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
| `backup_local_repo` | Backs up a single local git repository to Google Drive. |
| `run_precommit_scan` | Runs a pre-commit scan for sensitive data in a local directory. |

## Quick Start

### Prerequisites

1.  **`consult` CLI installed**:
    ```bash
    pipx install .
    ```

2.  **Backup Configuration** (Required for `backup_local_repo`):
    ```bash
    consult backup config
    ```
    Follow the prompts to configure the Google Drive folder ID.

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
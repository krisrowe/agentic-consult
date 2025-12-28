# Agentic Consult MCP Server (`consult-mcp`)

A **Model Context Protocol (MCP)** server that exposes the `agentic-consult` tools to AI assistants like Gemini CLI and Claude Desktop.

## What is MCP?

The [Model Context Protocol](https://modelcontextprotocol.io/) enables AI assistants to securely connect to external tools. This server exposes:

- **Backup Tools**: Backup local git repositories to Google Drive.
- **Security Tools**: Scan local directories for sensitive data (secrets, customer names) before committing.

## Features

### Tools (Actions)

| Tool | Description |
|------|-------------|
| `analyze_resources` | Analyzes local markdown documentation and resources using Gemini. |
| `backup_local_repo` | Backs up a single local git repository to Google Drive. |
| `run_precommit_scan` | Runs a pre-commit scan for sensitive data in a local directory. |

## Quick Start

### Prerequisites

1.  **`consult` CLI installed**:
    ```bash
    pip install -e .
    ```

2.  **Backup Configuration** (Required for `backup_local_repo`):
    ```bash
    consult backup config
    ```
    Follow the prompts to configure the Google Drive folder ID.

3.  **MCP Client**: Gemini CLI, Claude Code, or similar.

### Step 1: Register the Server with Gemini CLI

Register the `consult-mcp` server globally for your user.

```bash
gemini mcp add consult consult-mcp --stdio --scope user
```

The server uses **stdio transport**, meaning the Gemini client manages its lifecycle automatically.

### Step 2: Verify

Check the status:

```bash
gemini mcp list
```

You should see `consult` listed with a "Connected" status.

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

- **"Command not found: consult-mcp"**: Ensure you have installed the package (`pip install -e .`) and your virtual environment is active or the script is in your PATH.
- **Backup Errors**: Ensure you have run `consult backup config` to set the destination Drive folder.

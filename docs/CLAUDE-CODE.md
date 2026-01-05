# Claude Code CLI Setup (`consult-mcp`)

This guide covers how to connect Claude Code CLI to the `consult-mcp` server for email triage, backup management, and security scanning.

## Overview

The `consult-mcp` server uses **stdio transport**, which is the recommended integration method for Claude Code CLI. The client manages the server's lifecycle automatically—starting it when a session begins and stopping it when the session ends.

## Prerequisites

1. **`consult` CLI installed**:
   ```bash
   pipx install .
   ```

2. **Gemini API Key**: Required for AI-powered features like `triage_emails` and `analyze_files`. Get one from [Google AI Studio](https://aistudio.google.com/apikey).

## Quick Setup

Register the `consult-mcp` server with your Gemini API key:

```bash
claude mcp add --scope user consult -e 'GEMINI_API_KEY=your-api-key-here' -- consult-mcp
```

**What this does:**
- Registers `consult-mcp` as a user-level MCP server
- Stores the API key in `~/.claude.json` (passed to server at runtime)
- Uses stdio transport (client manages server lifecycle)

**Security note:** The key is stored in your local Claude config file. This is standard practice for CLI tools (similar to `~/.config/gcloud/`). Ensure the file isn't synced to untrusted locations.

## How It Works

When you interact with Claude Code and use consult tools, the Claude client:
1. Looks up the `consult` server in its configuration (`~/.claude.json`)
2. Finds the registered command: `consult-mcp`
3. Executes that command with the configured environment variables
4. Communicates with the process over stdin/stdout
5. Terminates the process when the interaction is complete

## Verifying the Setup

Check registered MCP servers:

```bash
claude mcp list
```

You should see `consult` listed. To test the connection, start a new Claude Code session and try:

```
triage emails
```

If you see an error about `GEMINI_API_KEY not found`, verify:
1. The key is set in your shell: `echo $GEMINI_API_KEY`
2. The MCP server was registered with the `-e` flag (check `~/.claude.json`)

## Configuration Result

After running the setup command, your `~/.claude.json` will contain:

```json
{
  "mcpServers": {
    "consult": {
      "type": "stdio",
      "command": "consult-mcp",
      "args": [],
      "env": {
        "GEMINI_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

## Troubleshooting

### "GEMINI_API_KEY not found"

1. Check the MCP registration includes the API key:
   ```bash
   grep -A10 '"consult"' ~/.claude.json
   ```

2. If missing or incorrect, re-register:
   ```bash
   claude mcp remove consult --scope user
   claude mcp add --scope user consult -e 'GEMINI_API_KEY=your-api-key-here' -- consult-mcp
   ```

3. **Restart Claude Code** for changes to take effect.

### "Command not found: consult-mcp"

Ensure the package is installed and in your PATH:
```bash
pipx install . --force
which consult-mcp
```

### Connection Errors

Test the server directly:
```bash
consult-mcp
```

This should start the MCP server in stdio mode. Press Ctrl+C to exit.

## Related Documentation

- [MCP-SERVER.md](../MCP-SERVER.md) - Full tool reference and Gemini CLI setup
- [README.md](../README.md) - CLI usage and authentication setup

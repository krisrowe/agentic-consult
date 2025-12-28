# Gemini CLI Setup (`consult`)

This guide covers how to connect Gemini CLI to the `agentic-consult` tools using the `consult-mcp` server.

## Overview

The `consult-mcp` server uses **stdio transport**. This means the Gemini CLI client manages the server's lifecycle automatically—starting it when a session begins and stopping it when the session ends.

## Quick Setup

Register the `consult-mcp` server globally for your user:

```bash
gemini mcp add consult consult-mcp --stdio --scope user
```

## Verifying the Setup

You can see all registered MCP servers by running:

```bash
gemini mcp list
```

A successful connection will show a `✓` and "Connected" status next to the `consult` entry.

## Usage

Once registered, you can ask Gemini to perform actions exposed by the server:

- **"Backup this repository to Drive"**: Triggers `backup_local_repo`.
- **"Scan for secrets before I commit"**: Triggers `run_precommit_scan`.
- **"Explain the project structure"**: Triggers `analyze_resources`.

## Troubleshooting

- **"Server not found: consult"**: Run `gemini mcp list` to check registration.
- **"Command not found"**: Ensure `consult-mcp` is in your PATH. If installed via `pip install -e .` in a virtualenv, you must be in that environment or use the full path to the script.

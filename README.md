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

## Installation

```bash
# Create virtual environment and install
make build

# Or manually
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## Quick Start

1. **Initialize a customer:**
```bash
consult customers init --slug acme --name "Acme Corp"
```

2. **Run precommit scan:**
```bash
consult precommit
# Or via make
make precommit
```

3. **Run tests:**
```bash
make test
```

## Key Commands

### Customer Management
```bash
# List/show customer
consult customers show <slug>

# Add note
consult customers notes add <slug> --content "Meeting notes..."

# Backup customer data
consult backup
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

### Configuration
```bash
# Show config
consult config show

# Set config value
consult config set customers-local-path /path/to/customers

# TickTick Integration (Optional)
# Requires TICKTICK_ACCESS_TOKEN environment variable
export TICKTICK_ACCESS_TOKEN="your-token-here"
```

> [!NOTE]
> A broader solution for automatic token discovery is pending. For now, ensure this environment variable is set if you want TickTick integration.

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

## Configuration Files

- **Customer config**: `~/.config/agentic-consult/customers/<slug>/customer.yaml`
  - **Note**: The slug should typically be the customer's email domain without the suffix (e.g., "acme" for "acme.com"). If the slug differs from the email domain, add the domain name (without suffix) to keywords to help detect customer data.
- **Global config**: `~/.config/agentic-consult/config.yaml`
- **Example templates**: `customer.yaml.example`, `config.yaml.example`

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

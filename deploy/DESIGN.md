# Cloud Deployment Design

Architecture and design rationale for the cloud deployment system.

For operational commands and usage, see [README.md](README.md).

## Overview

The email triage system consists of two Cloud Run Jobs orchestrated by Cloud Scheduler:

```
┌────────────────────────────────────────────────────────────────┐
│                     Cloud Scheduler                            │
│  ┌──────────────────┐          ┌──────────────────┐           │
│  │ trigger-email-   │          │ trigger-email-   │           │
│  │ fetch            │          │ analysis         │           │
│  │ (every N mins)   │          │ (offset by 5min) │           │
│  └────────┬─────────┘          └────────┬─────────┘           │
└───────────┼─────────────────────────────┼─────────────────────┘
            │                             │
            ▼                             ▼
┌──────────────────────┐      ┌──────────────────────┐
│   gmex-fetcher       │      │   consult-analyzer   │
│   (Cloud Run Job)    │      │   (Cloud Run Job)    │
│                      │      │                      │
│   Fetches emails     │      │   Analyzes emails    │
│   from Gmail API     │      │   using Gemini       │
└──────────┬───────────┘      └──────────┬───────────┘
           │                             │
           ▼                             ▼
┌────────────────────────────────────────────────────────────────┐
│                     GCS Bucket                                 │
│                   /email-archive/                              │
│                                                                │
│   *.meta          - Email metadata                             │
│   *.body          - Email content                              │
│   *.analysis.json - Gemini analysis (sidecar)                  │
└────────────────────────────────────────────────────────────────┘
```

## Repository Responsibilities

| Repo | Artifact | Responsibility |
|------|----------|----------------|
| `gmail-extractor` | `gcr.io/.../gmex-fetcher` | Fetch emails from Gmail, store in archive |
| `agentic-consult` | `gcr.io/.../consult-analyzer` | Analyze emails with Gemini |
| `agentic-consult` | Terraform + CLI | Deploy and manage both jobs |

Each repo owns its Docker image. The terraform in agentic-consult references both images.

## Resource Discovery & Configuration

### Design Principles

1. **GCP labels are source of truth** for resource discovery
2. **Minimal local config** - only store what's needed, discover the rest
3. **Zero-knowledge setup** - users shouldn't need to memorize IDs

### Label Scheme

| Resource | Label Key | Label Value | Purpose |
|----------|-----------|-------------|---------|
| GCP Project | `agentic-consult` | varies (`default`, `prod`, etc.) | Identify which project |
| GCS Bucket | `agentic-consult` | always `default` | Identify THE bucket in a project |

### What's Stored Locally vs Discovered

| Value | Stored in config? | Why |
|-------|-------------------|-----|
| `project_id` | Yes | Stable, fundamental scope identifier |
| `bucket_name` | Yes | Saved by `init`, validated by `deploy` |

**Rationale**: Both values are stored locally for fast, offline access (especially for terraform `resolve` during tests). To prevent staleness, `deploy` validates that the configured bucket matches the labeled bucket in GCP before running terraform. If they diverge, the user must re-run `init`.

**Intentional Design: `project_id` is write-protected**. There is no direct way for users to set `project_id` in config. It is only written by a successful `init` command after validating that the project exists and is accessible. This ensures that the config always reflects a validated, working project. If the configured project becomes inaccessible, `init` will fail with a helpful error message directing the user to verify their access or use `--project` to specify a different project.

### Multi-Environment Model

This design supports **multiple projects as environments**, not multiple environments per project:

```
Project A (agentic-consult=prod)
  └── Bucket (agentic-consult=default)

Project B (agentic-consult=staging)
  └── Bucket (agentic-consult=default)
```

To switch environments, run `init` targeting a different project label:
```bash
./cloud init prod      # uses agentic-consult=prod
./cloud init staging   # uses agentic-consult=staging
```

The environment alias is used only for discovery - only the concrete `project_id` is saved.

### CLI/Terraform Decoupling

**Critical Design Decision**: Terraform and the CLI are **fully decoupled**. Terraform does NOT call any Python code from the repository.

#### The Problem (Why We Decoupled)

When you install the CLI via `pipx`, you get a frozen snapshot of the code at that version. But when you `git clone` the repo to run terraform, you get a potentially different version. If terraform called Python code from the repo (e.g., via `data "external"`), you'd have:

- **CLI version A** installed via pipx (stable, tested)
- **Terraform calling version B** from the git clone (potentially newer/different)

This creates subtle bugs where terraform uses different logic than the CLI, and makes the system harder to reason about.

#### The Solution (Input Variables)

Terraform uses **input variables** (`-var` flags) instead of calling Python:

```hcl
variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "bucket_name" {
  description = "GCS bucket name for email archive"
  type        = string
}

variable "analyzer_tag" {
  description = "Image tag for consult-analyzer"
  type        = string
}
```

The CLI's `deploy` command:
1. Resolves git ref to SHA
2. Checks GCR for existing images, builds/pushes if needed
3. Runs terraform with all variables filled in

Users run `./cloud deploy` and the CLI handles terraform internally.

#### Benefits

1. **Version safety**: Terraform logic is self-contained; CLI version doesn't affect it
2. **Testability**: Terraform can be validated without Python dependencies
3. **Transparency**: Users see exactly what terraform commands will run
4. **Flexibility**: Can run terraform directly without the CLI if needed

#### SDK/CLI Separation

The cloud module follows a consistent SDK/CLI separation:

| Layer | Function | Returns |
|-------|----------|---------|
| SDK | `read_cloud_status(provider, project_id)` | `CloudStatus` dataclass |
| SDK | `pre_deploy(provider, project_id, bucket_name)` | `PreDeployResult` dataclass |
| CLI | `./cloud status` | Formatted text output |
| CLI | `./cloud pre-deploy` | Text or JSON (`--format` flag) |

The SDK functions are pure data; they return structured objects. The CLI formats them for human consumption or passes them through as JSON for machine consumption.

### Staleness Prevention

Since `resolve` reads from local config (not GCP), staleness is prevented at deploy time:

1. **`deploy` validates** that the configured `bucket_name` matches the labeled bucket in GCP
2. **If mismatch detected**, user is prompted to re-run `init`
3. **`--skip-config-check`** flag available if validation needs to be bypassed

This design allows tests to run without network access while still catching config drift before actual deployment.

### Testing

Terraform validation tests can run without GCP access:
- Test creates a fake config with `project_id` and `bucket_name`
- `resolve` reads from config (no network calls)
- Terraform validates syntax without hitting GCP

## Zero-Install Design (`./cloud`)

### Rationale

Deployment tools should be **repo-centric**. Every major deployment tool (Terraform, CDK, Pulumi, Serverless, Ansible) runs from the directory containing configuration files. They don't install globally and deploy arbitrary projects.

Installing a global CLI for deployment creates problems:
1. **Version mismatch**: Installed CLI version may differ from repo code
2. **Implicit dependencies**: Must remember to update CLI when updating repo
3. **Environment pollution**: Global install affects all projects

### Design Decision

All cloud administration and deployment commands are available via `./cloud`, a stdlib-only dispatcher in the repo root. **No pip, no venv, no pipx required** - just Python 3.10+.

```bash
# After git clone, immediately usable:
./cloud status
./cloud init --project=my-project
./cloud pre-deploy
./cloud scheduler list
./cloud image build
```

The `./cloud` dispatcher routes to modular scripts in `deploy/scripts/`, all using only Python standard library plus the repo's own `agentic_consult.cloud` SDK (which is also stdlib-only).

### What Uses Venv (via Make)

Virtual environments are **only** used for testing, wrapped in Make targets:

| Command | Purpose | Why venv needed |
|---------|---------|-----------------|
| `make test` | Run unit tests | pytest |
| `make test-integration` | Run integration tests | pytest |
| `make precommit` | Pre-commit checks | pytest + scanner |

These are developer workflows, not deployment workflows. Users running `make test` are developing, not deploying.

### Architecture

```
./cloud                      # Dispatcher (stdlib, executable via shebang)
deploy/scripts/
  _common.py                 # Shared utilities (colors, prompts, config)
  init.py                    # Full init with interactive prompts
  status.py                  # Show cloud status
  pre_deploy.py              # Check readiness, output terraform commands
  scheduler.py               # Scheduler management
  image.py                   # Docker build/push
```

Each script can also be run directly: `python deploy/scripts/status.py --help`

### Why Not Click/Typer?

Click is excellent for large CLIs with many nested commands. For ~10 deployment commands:
- **argparse** (stdlib) is sufficient and adds zero dependencies
- Interactive prompts use `input()` and `getpass.getpass()`
- Colors use simple ANSI codes

The slight verbosity cost is worth the zero-install benefit.

### Relationship to `consult` CLI

| Tool | Installed via | Purpose | Audience |
|------|---------------|---------|----------|
| `./cloud` | git clone | Deployment, cloud admin | Server Admin (has repo) |
| `consult` | pipx | MCP server, daily tools | Agent User (may not have repo) |
| `consult-mcp` | pipx | Run local MCP server | Agent User (local MCP) |

The `consult` CLI still exists for users who don't have the repo cloned (e.g., running local MCP server). But for deployment, use `./cloud`.

## MCP Server Architecture

### Transport Options

The MCP server supports two transports with **shared tools**:

```
agentic_consult/mcp/
  server.py      # FastMCP + all tools (pure shared, no transport)
  stdio.py       # Stdio transport wrapper
  http.py        # FastAPI + auth middleware (HTTP only)
```

| Component | File | Shared? |
|-----------|------|---------|
| Tools (backup, triage, scan, etc.) | `mcp/server.py` | ✓ Yes |
| FastMCP instance | `mcp/server.py` | ✓ Yes |
| Stdio transport (`mcp.run()`) | `mcp/stdio.py` | No - stdio only |
| HTTP transport (`mcp.streamable_http_app()`) | `mcp/http.py` | No - http only |
| Auth middleware (PAT check) | `mcp/http.py` | No - http only |
| Health endpoint (`/health`) | `mcp/http.py` | No - http only |

Entry points:
```
consult-mcp       → mcp/stdio.py:run_server()       # stdio (pipx install)
```

HTTP has **no entry point** - it runs via uvicorn in Docker:
```dockerfile
CMD ["uvicorn", "agentic_consult.mcp.http:app", "--host", "0.0.0.0", "--port", "8080"]
```

This keeps `consult-mcp-http` out of users' PATH. HTTP deps are optional:
```bash
pipx install agentic-consult        # stdio only, no HTTP deps
pip install agentic-consult[http]   # includes FastAPI, uvicorn (Docker)
```

### User Authentication (HTTP)

HTTP transport uses Personal Access Token (PAT) authentication:

| Secret | Location | Purpose |
|--------|----------|---------|
| `mcp-personal-access-token` | Secret Manager | Server reads at startup |
| `personal_access_token` | Local `settings.json` | Client sends with requests |

**Auth flow:**
1. Request includes `Authorization: Bearer <PAT>` header OR `?token=<PAT>` query param
2. Server validates against secret from Secret Manager
3. `/health` endpoint bypasses auth (for connectivity checks)

**Logging:**
- Valid token → `logger.info`
- Invalid/missing token → `logger.error` (for diagnostics)

### Admin vs User Separation

**Why two separate command sets?**

The admin and user are fundamentally different personas with different capabilities:

| Persona | Has repo? | Has gcloud? | Cloud access? |
|---------|-----------|-------------|---------------|
| Server Admin | ✓ Yes | ✓ Yes | Direct (Secret Manager, Cloud Run) |
| MCP User | ✗ No | ✗ No | None (only knows URL + PAT) |

**Design constraints:**

1. **User has NO gcloud** - They `pipx install agentic-consult` and that's it. No GCP SDK, no service account, no cloud CLI.

2. **User has NO repo** - They don't clone the repo. They just install the package and use the MCP server.

3. **No shared auth SDK** - Admin commands talk to Secret Manager directly. User commands only read/write local config files. These are completely separate code paths.

4. **Export/Import pattern** - Admin generates credentials and exports them. User receives credentials out-of-band (email, Slack, etc.) and imports them. This is the same pattern used by `food-agent`.

**Rationale:**

- Keeps user experience simple (no cloud setup required)
- Prevents users from accidentally modifying cloud resources
- Allows admin to control who gets access
- Works for users who only want to consume the service, not deploy it

### Admin vs User Commands

**Server Admin** (`./cloud` - has repo + gcloud):

```bash
./cloud user-auth init      # creates PAT in Secret Manager
./cloud user-auth regen     # rotates PAT (prompts unless --force)
./cloud user-auth status    # checks Secret Manager
./cloud user-auth export    # outputs URL + PAT as YAML
```

**MCP User** (`consult mcp` - pipx only, NO gcloud):

```bash
consult mcp import          # reads YAML from stdin, saves to local config
consult mcp status [--test] # shows config, optionally validates connectivity
consult mcp register gemini [--dry-run]
consult mcp register claude [--dry-run]
consult mcp register url    # outputs URL with embedded token
```

### Config Storage

Single file (`settings.json`), different keys per persona:

```json
{
  "project_id": "my-project",
  "bucket_name": "my-bucket",
  "mcp_url": "https://consult-mcp-xxx.run.app",
  "personal_access_token": "abc123..."
}
```

| Key | Written by | Read by |
|-----|------------|---------|
| `project_id` | `./cloud init` | `./cloud *` |
| `bucket_name` | `./cloud init` | `./cloud *` |
| `mcp_url` | `consult mcp import` | `consult mcp *` |
| `personal_access_token` | `consult mcp import` | `consult mcp *` |


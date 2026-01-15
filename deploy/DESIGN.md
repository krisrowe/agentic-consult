# Cloud Deployment Design

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

## Commands

For step-by-step deployment instructions, see [README.md](../README.md#cloud-deployment).

| Command | Purpose |
|---------|---------|
| `./cloud init` | Initialize project, bucket, secrets |
| `./cloud status` | Show current cloud resource status (read-only) |
| `./cloud pre-deploy` | Check readiness and output terraform commands |
| `./cloud scheduler list` | View scheduler jobs and schedules |
| `./cloud scheduler set <job> <mins>` | Update job frequency |
| `./cloud image build` / `push` | Build and push analyzer image |

## Terraform Behavior

The terraform creates schedulers with default schedules but uses `lifecycle { ignore_changes = [schedule] }` so that:

1. **First deploy**: Creates with default schedule (30 min)
2. **Subsequent deploys**: Does NOT overwrite manual schedule changes
3. **CLI is source of truth**: Use `./cloud scheduler set` to change schedules

## Required Secrets

| Secret ID | Description | Used By |
|-----------|-------------|---------|
| `gemini-api-key` | Gemini API key | analyzer |
| `gmail-token` | Gmail OAuth token JSON | fetcher |

Secrets are created/updated via `./cloud init`. See [README.md](../README.md#cloud-deployment) for the full deployment workflow.

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

### Init Scenarios

| User knows | Command | What happens |
|------------|---------|--------------|
| Nothing | `./cloud init` | Searches `agentic-consult=default`, finds project |
| Project ID | `./cloud init --project=xyz` | Uses `xyz` directly, skips label search |

Environment alias support (`init prod` for `agentic-consult=prod`) is tracked in [#24](https://github.com/krisrowe/agentic-consult/issues/24).

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
```

The CLI's `pre-deploy` command:
1. Reads configuration from local settings
2. Checks deploy readiness via the cloud SDK
3. Outputs the full terraform commands with variables filled in

```bash
$ ./cloud pre-deploy

Ready to deploy. Run:

  cd deploy/terraform
  terraform init
  terraform apply -var="project_id=my-project" -var="bucket_name=my-bucket"
```

Users copy-paste these commands to run terraform. The CLI never invokes terraform directly.

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

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

## CLI Commands

For step-by-step deployment instructions, see [README.md](../README.md#cloud-deployment).

| Command | Purpose |
|---------|---------|
| `consult cloud config init` | Initialize project, bucket, secrets |
| `consult cloud deploy` | Run terraform to create infrastructure |
| `consult cloud scheduler list` | View scheduler jobs and schedules |
| `consult cloud scheduler set <job> <mins>` | Update job frequency |
| `consult image build` / `push` | Build and push analyzer image |

## Terraform Behavior

The terraform creates schedulers with default schedules but uses `lifecycle { ignore_changes = [schedule] }` so that:

1. **First deploy**: Creates with default schedule (30 min)
2. **Subsequent deploys**: Does NOT overwrite manual schedule changes
3. **CLI is source of truth**: Use `consult cloud scheduler set` to change schedules

## Required Secrets

| Secret ID | Description | Used By |
|-----------|-------------|---------|
| `gemini-api-key` | Gemini API key | analyzer |
| `gmail-token` | Gmail OAuth token JSON | fetcher |

Secrets are created/updated via `consult cloud config init`. See [README.md](../README.md#cloud-deployment) for the full deployment workflow.

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
consult cloud config init prod      # uses agentic-consult=prod
consult cloud config init staging   # uses agentic-consult=staging
```

The environment alias is used only for discovery - only the concrete `project_id` is saved.

### Init Scenarios

| User knows | Command | What happens |
|------------|---------|--------------|
| Nothing | `consult cloud config init` | Searches `agentic-consult=default`, finds project |
| Project ID | `consult cloud config init --project=xyz` | Uses `xyz` directly, skips label search |

Environment alias support (`init prod` for `agentic-consult=prod`) is tracked in [#24](https://github.com/krisrowe/agentic-consult/issues/24).

### Terraform Integration & paths.py Pattern

Terraform gets coordinates via an external data source that runs `paths.py` directly:

```hcl
data "external" "project_info" {
  program = ["python3", "${path.module}/../../agentic_consult/paths.py"]
}
```

#### The paths.py Pattern (Intentional - Preserve During Refactoring)

`agentic_consult/paths.py` is a **dual-purpose module** that can be:

1. **Imported as a library** by CLI, SDK, MCP code:
   ```python
   from agentic_consult.paths import get_settings_dir, load_settings
   ```

2. **Run directly as a script** (no package install needed):
   ```bash
   python3 agentic_consult/paths.py
   # Outputs: {"project_id": "...", "bucket_name": "..."}
   ```

**Key constraints** (preserve these):
- **Stdlib only** - no external dependencies (os, json, pathlib only)
- **Self-contained** - all path resolution logic lives here
- **`if __name__ == "__main__"`** block outputs JSON for terraform

This pattern is used in other repos (e.g., `gmex_sdk/paths.py` in gmail-extractor, where Makefile uses it to export env vars for Docker - that one outputs shell `KEY=value` format for `eval`, ours outputs JSON for terraform). The pattern should be preserved during refactoring. The `config.py` module imports from `paths.py` to avoid duplication.

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

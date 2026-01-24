# Cloud Deployment

Operational guide for deploying and managing the email triage system.

For architecture and design rationale, see [DESIGN.md](DESIGN.md).

## Commands

| Command | What it does |
|---------|--------------|
| `./cloud deploy` | Deploy everything from HEAD |
| `./cloud deploy --ref abc123` | Deploy everything from specific ref |
| `./cloud deploy mcp` | Deploy only MCP service |
| `./cloud deploy analyzer` | Deploy only analyzer job |
| `./cloud deploy fetcher` | Deploy only fetcher job |
| `./cloud deploy config` | Sync config files to GCS (no image build) |
| `./cloud status` | Show alignment across all layers |
| `./cloud init` | First-time setup (project, bucket, secrets) |

## How It Works

One command does everything:

```
./cloud deploy [component] [--ref X]
         │          │           │
         │          │           └── Git ref (default: HEAD)
         │          └── Optional: mcp, analyzer, fetcher, config
         └── Handles: GCR check → build → push → terraform
```

### What Happens

```bash
./cloud deploy --ref abc123
```

1. **Get ref** → `abc123` (or HEAD SHA if no `--ref`)
2. **Check GCR** → Does `consult-analyzer:abc123` exist?
3. **Build if needed** → `docker build -t gcr.io/$PROJECT/consult-analyzer:abc123`
4. **Push if needed** → `docker push`
5. **Terraform apply** → `terraform apply -var="image_tag=abc123" -var="fetcher_tag=v1.0.0"`

Terraform detects if Cloud Run needs updating. If tag unchanged, no-op.

### Single Component Deploy

```bash
./cloud deploy mcp --ref abc123
```

- Only builds/pushes the MCP image
- Uses `terraform apply -target=google_cloud_run_v2_service.mcp_service`
- Other services untouched

### Cross-Repo Dependency (gmex-fetcher)

The fetcher image comes from `gmail-extractor` repo. Version pinned in `images.ini`:

```ini
[fetcher]
image = gmex-fetcher
repo = https://github.com/krisrowe/gmail-extractor
ref = v1.0.0   # Pin to semver tag, not 'master'
```

When you deploy:
- `image_tag` → ref you specify, or HEAD SHA if no `--ref` (used for both analyzer and mcp)
- `fetcher_tag` → ref from `images.ini` at that commit

To upgrade gmex: update `images.ini`, commit, deploy.

## Idempotency

| Scenario | What happens |
|----------|--------------|
| Image in GCR, deployed | GCR check (1 sec), terraform no-op |
| Image in GCR, not deployed | GCR check, terraform updates Cloud Run |
| Image not in GCR | Build, push, terraform updates Cloud Run |

Nothing runs that doesn't need to. Everything runs that does.

## Working Directory State

**Dirty working directory is ignored.** Deploy always uses a git ref (defaulting to HEAD).

```bash
# These are equivalent if HEAD is abc123:
./cloud deploy
./cloud deploy --ref HEAD
./cloud deploy --ref abc123
```

Uncommitted changes are never deployed. This is how CI/CD works.

### How It Works Internally

Docker builds from filesystem, not git. So we extract the ref to a temp dir:

```bash
# Extract ref to temp dir, build from there
git archive --format=tar $REF | tar -x -C /tmp/build-context
docker build -t gcr.io/$PROJECT/analyzer:$REF /tmp/build-context
```

Working dir untouched. Dirty state irrelevant.

## Mismatched Components

Each component can be deployed independently at different refs:

```bash
./cloud deploy mcp --ref abc123       # MCP at abc123
./cloud deploy analyzer --ref def456  # Analyzer at def456
./cloud deploy fetcher                # Fetcher at HEAD's images.ini ref
```

Use cases:
- Roll back just one component
- Test new analyzer with old MCP
- Deploy hotfix to MCP without touching others

Use `./cloud status` to see what's deployed where.

## Status Command

```bash
./cloud status
```

Shows alignment across all layers:

```
Component     Local HEAD    GCR           Cloud Run
─────────────────────────────────────────────────────
analyzer      abc123        abc123        abc123       ✓
mcp           abc123        def456        def456       ✗ (local ahead)
fetcher       v1.0.0        v1.0.0        v0.9.0       ✗ (GCR ahead)
```

## Terraform Variables

Two variables control image tags:

```hcl
variable "image_tag" {
  type        = string
  description = "Tag for internal images (analyzer, mcp) - same repo, same ref"
}

variable "fetcher_tag" {
  type        = string
  description = "Tag for fetcher image (from images.ini ref)"
}

locals {
  analyzer_image = "gcr.io/${var.project_id}/consult-analyzer:${var.image_tag}"
  mcp_image      = "gcr.io/${var.project_id}/consult-mcp:${var.image_tag}"
  fetcher_image  = "gcr.io/${var.project_id}/gmex-fetcher:${var.fetcher_tag}"
}
```

Deploy script always passes both vars. `-target` controls scope:

```bash
# Full deploy
terraform apply -var="image_tag=abc123" -var="fetcher_tag=v1.0.0"

# Single component
terraform apply -target=google_cloud_run_v2_service.mcp_service -var="image_tag=abc123" -var="fetcher_tag=v1.0.0"
```

## Prerequisites

- Python 3.10+
- `gcloud` CLI authenticated
- `terraform` installed
- Docker

## First-Time Setup

```bash
./cloud init              # discovers project, creates bucket
./cloud deploy            # builds, pushes, deploys everything
```

## Secrets

| Secret ID | Description | Used By |
|-----------|-------------|---------|
| `gemini-api-key` | Gemini API key | analyzer, mcp |
| `gmail-token` | Gmail OAuth token JSON | fetcher, mcp |
| `mcp-access-token` | MCP personal access token | mcp |

Created via `./cloud init`.

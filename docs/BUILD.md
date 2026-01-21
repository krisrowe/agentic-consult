# Build and Versioning System

This document describes the build, versioning, and deployment workflow for agentic-consult.

## Design Goals

1. **Traceability** - Always know which version is deployed
2. **Reproducibility** - Any tag can be rebuilt identically
3. **Simplicity** - Minimize custom tooling, use conventional patterns
4. **Fast iteration** - Templates can be updated without image rebuild

## Versioning Strategy

### Recommended: CalVer + Build Number

Format: `YYYY.MM.BUILD` (e.g., `2026.01.3`)

**Why CalVer over SemVer:**
- This is an internal tool, not a library with API contracts
- Date-based versions immediately communicate freshness
- No ambiguity about "breaking changes" for internal services

**Alternatives considered:**
- SemVer (`1.2.3`) - Better for libraries with public APIs
- Git SHA only - No human-readable ordering
- Timestamp (`20260121.143022`) - Too granular, noisy

### Version Source of Truth

The version lives in `pyproject.toml`:
```toml
[project]
name = "agentic-consult"
version = "0.0.9"
```

This is read at runtime via `agentic_consult/__init__.py`:
```python
from agentic_consult import __version__, __package_name__
```

No hardcoded package names elsewhere - derived from module name convention.

## Image Tagging Convention

Each image is tagged with:
1. **Version tag**: `gcr.io/PROJECT/consult-mcp:2026.01.3`
2. **Latest tag**: `gcr.io/PROJECT/consult-mcp:latest`
3. **Git SHA tag**: `gcr.io/PROJECT/consult-mcp:sha-abc1234` (optional, for debugging)

**Terraform uses `:latest`** - This is intentional. Cloud Run pulls the latest image at deploy time. Version traceability comes from the container reporting its version on startup.

## Build Workflow

### Option A: Local Build (Recommended for Solo Dev)

```bash
# 1. Bump version in pyproject.toml
# 2. Run tests
make test

# 3. Build and push all images
./cloud images build all
./cloud images push all

# 4. Deploy
./cloud deploy

# 5. (Optional) Push templates to GCS
./cloud templates push
```

**Pros:** Simple, immediate, works offline
**Cons:** Relies on local Docker, manual version bumping

### Option B: Cloud Build (Recommended for Team/CI)

Trigger builds on git tag push:

```yaml
# cloudbuild.yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'gcr.io/$PROJECT_ID/consult-mcp:$TAG_NAME', '--target', 'mcp-http', '.']
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/$PROJECT_ID/consult-mcp:$TAG_NAME']
```

**Pros:** Reproducible, auditable, no local Docker needed
**Cons:** Requires GCP setup, slower iteration

### Option C: GitHub Actions

For teams using GitHub-centric workflows:

```yaml
# .github/workflows/build.yml
on:
  push:
    tags: ['v*']
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build and push
        run: |
          docker build -t gcr.io/${{ secrets.GCP_PROJECT }}/consult-mcp:${{ github.ref_name }} .
          docker push ...
```

**Pros:** Standard, well-documented, good for open source
**Cons:** Requires GitHub Actions setup, secrets management

## Version Reporting

### MCP Server Startup Log

The server logs its version on startup:

```python
from agentic_consult import __version__, __package_name__
logger.info(f"{__package_name__} MCP server v{__version__}")
```

This appears in Cloud Run logs, making it easy to verify deployed version.

### Health/Version Endpoint (Optional)

Add a simple endpoint for version checking:

```python
@mcp.tool()
async def get_server_info() -> dict:
    """Returns server version and configuration info."""
    return {
        "version": __version__,
        "template_source": get_template_source("email_triage.txt"),
    }
```

Or expose via HTTP if using the HTTP transport.

## Template Hot-Reload Workflow

Templates can be updated without rebuilding the Docker image:

```bash
# 1. Edit template locally
vim agentic_consult/templates/email_triage.txt

# 2. Push to GCS
./cloud templates push

# 3. Restart containers to pick up changes
./cloud restart mcp
```

**Note:** Docstrings are read at server startup, so container restart is required.

## Commands Reference

| Command | Description |
|---------|-------------|
| `./cloud images list` | Show image status and digests |
| `./cloud images build [target]` | Build Docker image(s) |
| `./cloud images push [target]` | Push to GCR |
| `./cloud deploy` | Apply Terraform (deploys services) |
| `./cloud templates push` | Sync templates to GCS |
| `./cloud restart [service]` | Force container restart |

## Debugging Deployed Version

1. **Check Cloud Run logs:**
   ```bash
   gcloud run services logs read consult-mcp --region=us-central1 --limit=50
   ```
   Look for startup log with version.

2. **Check image digest:**
   ```bash
   gcloud run services describe consult-mcp --region=us-central1 --format='value(spec.template.spec.containers[0].image)'
   ```

3. **Call version endpoint (if implemented):**
   ```bash
   curl -H "Authorization: Bearer $TOKEN" https://consult-mcp-xxx.run.app/info
   ```

## Release Checklist

1. [ ] Update version in `pyproject.toml`
2. [ ] Run `make test` - all tests pass
3. [ ] Run `make precommit` - no sensitive data
4. [ ] Build images: `./cloud images build all`
5. [ ] Push images: `./cloud images push all`
6. [ ] Deploy: `./cloud deploy`
7. [ ] Verify: Check logs for correct version
8. [ ] (If templates changed) `./cloud templates push && ./cloud restart mcp`
9. [ ] Tag release: `git tag v2026.01.3 && git push --tags`

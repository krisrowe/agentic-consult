# Test Suite Organization

## Configuration

See `pytest.ini` in the repo root:

```ini
[pytest]
addopts = -v
markers =
    slow: tests requiring public network (terraform registry, pip, etc.)
    integration: tests requiring user auth/config/infrastructure
testpaths = tests/unit tests/slow
```

## Directory Structure

```
tests/
  unit/           # Fast, offline tests (default)
  slow/           # Slow tests, public network only (default)
  integration/    # Requires user auth/config (manual only)
```

## What Runs by Default

`pytest` runs tests in `tests/unit/` and `tests/slow/` (configured via `testpaths` in pytest.ini).

Integration tests are **never** run by default - they require explicit invocation.

## Commands

| Command | What it runs |
|---------|--------------|
| `pytest` | unit + slow (CI-safe, gates PRs) |
| `pytest -m "not slow"` | unit only (fast, offline) |
| `pytest tests/integration` | integration only (needs your config) |
| `pytest tests/` | everything (unit + slow + integration) |
| `pytest tests/ -m "not slow"` | unit only from all folders |

## Markers

Tests are auto-marked via `conftest.py` in each directory:

| Marker | Applied to | Meaning |
|--------|------------|---------|
| `slow` | `tests/slow/**`, `tests/integration/**` | Requires network, takes time |
| `integration` | (manual decoration) | Requires user auth/config |

## When to Use Each Directory

### `tests/unit/`
- Fast, deterministic tests
- No network access required
- No external dependencies
- Should run in <1 second each

### `tests/slow/`
- Tests that download from public registries (terraform, pip, npm)
- Reliable but slow due to network
- Still CI-safe (no auth/secrets needed)
- Example: `terraform validate` tests

### `tests/integration/`
- Tests requiring your GCP project, secrets, or deployed services
- Not CI-safe (would fail without user's specific configuration)
- Run manually when you have the environment set up
- Example: Gmail API tests, live Cloud Run tests

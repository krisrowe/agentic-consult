# Contributing to Agentic Consult

Thank you for contributing! This guide covers the development workflow and testing requirements.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/krisrowe/agentic-consult.git
cd agentic-consult

# Build environment (creates .venv, installs deps, runs tests)
make build
```

## Before Every Commit

**CRITICAL**: Always run the precommit checks before committing:

```bash
make precommit
```

This command:
1. **Runs pytest** - All 10 tests must pass
2. **Runs security scanner** - No sensitive data in staged files

**Never skip this step!** It prevents:
- Broken tests from being committed
- Customer data leaks
- Personal information exposure
- API keys/tokens from being committed

## Testing

### Running Tests

```bash
# Run unit tests only (fast)
make test

# Run integration tests (slower, hits real APIs)
make test-integration

# Run all tests (unit + integration)
make test-all

# Or manually with pytest
source .venv/bin/activate
pytest tests/unit

# Verbose output
pytest -v

# Specific test file
pytest tests/unit/test_precommit.py
```

### Test Suite Coverage

See **[TESTING.md](TESTING.md)** for detailed testing strategy (**["Sociable Unit Tests"](https://martinfowler.com/bliki/UnitTest.html)** vs. "External").

**Core Tests (Unit):**
- Schema validation
- Security scanner validation
- Backup workflows (mocked I/O)
- Gitignore behavior

**External Tests:**
- End-to-end backup workflows (hitting Drive)
- Gemini API interactions
- Gmail/Refresh command workflows

### Adding New Tests

1. Add test file to `tests/unit/` or `tests/integration/`
2. Use pytest fixtures and assertions
3. Test with synthetic data only (never real customer names/data)
4. Run `make test` or `make test-integration` to verify
5. Run `make precommit` before committing

## Code Style

- Follow existing patterns in the codebase
- Keep functions focused and documented
- Use type hints where helpful
- Test new scanner rules thoroughly

## Security Scanner

The `consult precommit` scanner detects:
- Customer names, slugs, keywords
- Email addresses
- Google Drive folder IDs
- API keys/tokens
- Local usernames

**Test your scanner changes:**
```bash
# Test on current repo
consult precommit

# Include gitignored files
consult precommit --include-ignored
```

## Design Principles

1.  **Favor Sociable Unit Tests**: Avoid mocking internal project collaborators. Mock only at the system boundary (Network I/O, Third-Party APIs). See [TESTING.md](TESTING.md).
2.  **SDK/CLI Separation**: Business logic belongs in the SDK (`agentic_consult/sdk/` or appropriate domain modules). The CLI (`agentic_consult/cli/`) is a thin wrapper.
3.  **Makefile-First Automation**: The `Makefile` is the primary interface for all development tasks.
    *   **One Command to Rule Them All**: Every task (testing, building, scanning) should be achievable through a single `make` command.
    *   **Zero Manual Setup**: Contributors should never need to manually create virtual environments, activate them, or install dependencies as separate steps.
    *   **Auto-Initialization**: Targets must automatically detect and repair missing prerequisites (like a missing `.venv`) before running.
    *   **Transparency**: While `make` provides a convenient shortcut, it should remain clear what is happening under the hood (e.g., by logging the steps being performed).

## Development Workflow

1. **Create feature branch**
   ```bash
   git checkout -b feature/your-feature
   ```

2. **Make changes**
   - Write code
   - Add/update tests
   - Update docs if needed

3. **Test locally**
   ```bash
   make test  # Must pass
   ```

4. **Run precommit**
   ```bash
   make precommit  # Must pass with no findings
   ```

5. **Commit**
   ```bash
   git add .
   git commit -m "Brief description of changes"
   ```

6. **Push and create PR**
   ```bash
   git push origin feature/your-feature
   ```

## Official Gemini CLI Usage

When using the `gemini` CLI for automated processing (e.g., in `customers refresh`), follow these best practices for clean, predictable, and fast output:

### Disabling Extensions and MCP
To prevent `gemini` from loading extensions or MCP servers (which is slow and can clutter output), use empty strings for the following flags. This reduces startup time from several seconds to milliseconds.

```bash
gemini --allowed-mcp-server-names "" --extensions "" "Your prompt"
```

### Requesting Raw JSON
Do not use `--output-format json` if you need raw JSON without the metadata envelope. Instead, request raw JSON in the prompt and return it directly.

**Example Prompt Snippet:**
```
Return ONLY a raw JSON object with the following structure. Do not include markdown code blocks, preamble, or any other text.
{
  "create": [...],
  "update": [...]
}
```

### Handling Output
Redirect `stderr` to `/dev/null` if you want to hide any remaining warnings or loading messages.

## Common Issues

**Tests failing:**
- Check virtual environment is activated
- Rebuild: `make clean && make build`
- Check for import errors

**Precommit scanner finding false positives:**
- Add patterns to `.gitignore` if appropriate
- Use synthetic test data (e.g., "FakeCorp", "TestCompany")
- Never use real customer names in tests

**Module not found errors:**
- Reinstall in dev mode: `pip install -e '.[dev]'`
- Or use: `make build`

## Questions?

Open an issue or contact the repository owner.

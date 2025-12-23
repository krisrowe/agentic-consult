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
# Run all tests (recommended)
make test

# Or manually with pytest
source .venv/bin/activate
pytest

# Verbose output
pytest -v

# Specific test file
pytest tests/unit/test_precommit.py
```

### Test Suite Coverage

**10 comprehensive tests:**
- Schema validation (customer.yaml, config.yaml)
- Drive ID detection and validation
- Security scanner with exact line/value matching
- Gitignore behavior verification
- Multiple match counting on non-adjacent lines

### Adding New Tests

1. Add test file to `tests/unit/`
2. Use pytest fixtures and assertions
3. Test with synthetic data only (never real customer names/data)
4. Run `make test` to verify
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

## Workflow

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

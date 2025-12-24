# Unit Testing Philosophy for Refresh Command

## Overview

This directory contains end-to-end unit tests for the `consult customers refresh` command. These tests exercise the full command flow while avoiding network I/O and minimizing the use of mocking frameworks.

## Testing Approach

### Core Principles

1. **End-to-End Execution**: Tests run the actual `consult customers refresh` command via Click's `CliRunner`, exercising the full code path from CLI entry point to completion.

2. **No Network I/O**: All tests avoid network calls by using:
   - `use_mock_data: true` in config to use local mock files instead of Gmail/TickTick APIs
   - `use_mock_gemini: true` to use `scripts/mock-gemini.sh` instead of real Gemini API
   - Mocked `subprocess.run` for TickTick CLI calls (minimal mocking, only for external process)

3. **Minimal Mocking**: We avoid mocking our own code. The only mocking is:
   - `subprocess.run` for external TickTick CLI calls (unavoidable external dependency)
   - This allows us to test the actual logic in `cli.py`, `refresh.py`, `gmail.py`, `ticktick.py`, etc.

4. **Isolated Filesystem**: Each test uses Click's `isolated_filesystem()` to create a temporary directory structure, ensuring tests don't interfere with each other or the user's actual data.

### Test Structure

Each test follows this pattern:

```python
def test_feature():
    runner = CliRunner()
    
    with runner.isolated_filesystem() as tmp_dir:
        # 1. Setup customer directory structure
        customers_dir = Path(tmp_dir) / 'customers'
        test_customer_dir = customers_dir / 'testcorp'
        
        # 2. Create customer.yaml
        (test_customer_dir / 'customer.yaml').write_text(...)
        
        # 3. Create mock data files
        (test_customer_dir / 'mock-emails.json').write_text(...)
        (test_customer_dir / 'mock-server-tasks.json').write_text(...)
        
        # 4. Create config.yaml with mock settings
        (customers_dir / 'config.yaml').write_text("""
use_mock_gemini: true
use_mock_data: true
skip_task_writes: false
""")
        
        # 5. Setup mock Gemini response
        (repo_root / 'mock-deltas.json').write_text(...)
        
        # 6. Mock subprocess for TickTick CLI
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(...)
            
            # 7. Run the actual command
            result = runner.invoke(
                main,
                ['customers', 'refresh', 'testcorp', '--no-dry-run'],
                env={'CUSTOMERS_DIR': str(customers_dir)}
            )
            
            # 8. Assert results
            assert result.exit_code == 0
            # ... verify files, state, etc.
```

### Mock Data Flow

When `use_mock_data: true`:
- **Gmail fetch**: Reads from `<customer_dir>/mock-emails.json` instead of calling `gwsa mail search`
- **TickTick fetch**: Reads from `<customer_dir>/mock-server-tasks.json` instead of calling `ticktick tasks list`
- **Gemini**: Uses `scripts/mock-gemini.sh` which returns content from `mock-deltas.json`

### Command-Line Flags

- `--skip-fetch`: Skip fetching from Gmail/TickTick, use cached `emails/emails.json` and `tasks/tasks.json`
- `--no-dry-run`: Actually execute (vs dry-run mode)
- `--skip-task-writes`: Skip writing to TickTick (for safe testing)
- `--expected-max-deltas N`: Safety limit on number of proposed changes

### Test Coverage

Tests should cover:
1. **Happy path**: Normal execution with expected inputs
2. **Edge cases**: Empty data, missing files, etc.
3. **State transitions**: First run vs subsequent runs
4. **Filtering logic**: Processed vs unprocessed emails
5. **Error handling**: Invalid data, failed commands

## Example Tests

### Email Processing Tracking

The `test_email_processing_tracking.py` module tests all 4 permutations of email processing:

1. **Local emails.json + already processed** → Skip
2. **Local emails.json + not processed** → Process
3. **Gmail query + already processed** → Skip
4. **Gmail query + not processed** → Process

Each test verifies:
- Correct emails are filtered/processed
- `emails_processed.txt` is updated correctly
- No network I/O occurs

## Running Tests

```bash
# Run all refresh tests
PYTHONPATH=. .venv/bin/pytest tests/unit/refresh/ -v

# Run specific test file
PYTHONPATH=. .venv/bin/pytest tests/unit/refresh/test_email_processing_tracking.py -v

# Run specific test
PYTHONPATH=. .venv/bin/pytest tests/unit/refresh/test_email_processing_tracking.py::test_local_emails_already_processed_are_skipped -v
```

## Benefits of This Approach

1. **High Confidence**: Tests exercise the actual code paths users will hit
2. **Fast**: No network I/O means tests run in milliseconds
3. **Maintainable**: Minimal mocking means tests don't break when refactoring internals
4. **Realistic**: Uses the same config/data structures as production
5. **Debuggable**: Easy to inspect the temporary filesystem during test failures

## Adding New Tests

When adding new tests:
1. Follow the established pattern above
2. Use `isolated_filesystem()` for isolation
3. Set `use_mock_data: true` and `use_mock_gemini: true`
4. Only mock `subprocess.run` for external CLI calls
5. Verify both success and failure cases
6. Test state changes (files created, updated, etc.)

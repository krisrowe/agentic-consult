"""Global test configuration - ensures ALL tests are isolated from real config.

HOW THIS WORKS
==============

1. FIXTURE EXECUTION (autouse=True)
   - This fixture runs ONCE PER TEST, not once globally
   - pytest executes it fresh before each test function

2. TEMP DIRECTORY ISOLATION (tmp_path)
   - tmp_path is a pytest built-in fixture
   - Creates a UNIQUE directory per test: /tmp/pytest-.../test_foo0/, /tmp/pytest-.../test_bar0/
   - Tests cannot see each other's files

3. ENV VAR AUTO-REVERT (monkeypatch)
   - monkeypatch.setenv() sets the env var for the test
   - pytest AUTO-REVERTS the change when the test ends
   - Next test starts with clean env

4. WHY CONFTEST.PY
   - Central place to define fixtures used by all tests
   - Code lives here but executes individually per test
   - No need to import or decorate - autouse=True handles it

WHAT THIS PROTECTS AGAINST
==========================
- Tests accidentally reading real ~/.config/agentic-consult/
- Tests writing to real user config (corruption)
- Tests affecting each other via shared state
- Forgetting to set CONSULT_CONFIG_DIR in individual tests

LIMITATIONS
===========
- Relies on all code paths using get_settings_dir() from paths.py
- Hardcoded paths that bypass CONSULT_CONFIG_DIR won't be isolated
- Not a hard sandbox (unlike Docker/pyfakefs)
"""
import pytest
from agentic_consult.paths import APP_SLUG
from agentic_consult.config import load_main_config

# Read REAL config at module load time, BEFORE any test isolation kicks in.
# This allows integration tests to access credentials via Secret Manager.
_real_settings = load_main_config()
_real_project_id = _real_settings.get("project_id")


@pytest.fixture
def real_project_id():
    """Project ID from real settings.json (read before test isolation).

    Use this in integration tests that need to access Secret Manager.
    Returns None if no project_id configured.
    """
    return _real_project_id


@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    """Auto-isolate every test from real config directories.

    Creates a unique temp config dir for each test.
    Uses package name (APP_SLUG) to avoid conflicts with other repos.
    See module docstring for how this works.
    """
    test_config_dir = tmp_path / APP_SLUG / "config"
    test_config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CONSULT_CONFIG_DIR", str(test_config_dir))




@pytest.fixture
def config_dir(tmp_path):
    """Returns the isolated config directory path for tests that need it.

    Use this instead of hardcoding tmp_path / "config".
    The directory is already created by isolate_config fixture.
    """
    return tmp_path / APP_SLUG / "config"

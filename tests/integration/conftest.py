"""Auto-apply 'slow' marker to all tests in this directory.

Integration tests require user auth/config and are not run by default.
Run explicitly with: pytest tests/integration
"""
import pytest

pytestmark = pytest.mark.slow


def pytest_configure(config):
    """Set longer timeout for integration tests (60s vs 2s for unit)."""
    config._inicache['timeout'] = 60

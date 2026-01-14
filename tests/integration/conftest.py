"""Auto-apply 'slow' marker to all tests in this directory.

Integration tests require user auth/config and are not run by default.
Run explicitly with: pytest tests/integration
"""
import pytest

pytestmark = pytest.mark.slow

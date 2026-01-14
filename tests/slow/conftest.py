"""Auto-apply 'slow' marker to all tests in this directory."""
import pytest

pytestmark = pytest.mark.slow

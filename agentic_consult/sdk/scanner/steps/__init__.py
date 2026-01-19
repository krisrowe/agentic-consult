"""Auto-discovery for scanner steps.

Each module in this package should have a run_checks(repo_path, deep=False) function
that returns a List[CheckResult].
"""

import pkgutil
import importlib
from typing import List, Callable

from ..utils import CheckResult


def discover_steps() -> List[tuple]:
    """Discover all step modules and their run_checks functions.

    Returns:
        List of (module_name, run_checks_func) tuples
    """
    steps = []
    for finder, name, ispkg in pkgutil.iter_modules(__path__):
        if name.startswith('_'):
            continue
        mod = importlib.import_module(f".{name}", __name__)
        if hasattr(mod, 'run_checks'):
            steps.append((name, mod.run_checks))
    return steps


def run_all_steps(repo_path: str, deep: bool = False,
                  only_step: str = None) -> List[CheckResult]:
    """Run all discovered steps and collect results.

    Args:
        repo_path: Path to git repository
        deep: If True, run deep/history checks
        only_step: If specified, run only this step module

    Returns:
        List of CheckResult from all steps
    """
    results = []
    for name, run_checks in discover_steps():
        if only_step is not None and name != only_step:
            continue
        try:
            step_results = run_checks(repo_path, deep=deep)
            results.extend(step_results)
        except Exception as e:
            results.append(CheckResult(
                name=f"{name} (error)",
                passed=False,
                findings=[str(e)],
                error=str(e)
            ))
    return results


def get_step_names() -> List[str]:
    """Get list of all discovered step module names."""
    return [name for name, _ in discover_steps()]

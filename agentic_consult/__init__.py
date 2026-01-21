"""agentic-consult: Email triage and workspace tooling."""

from importlib.metadata import version

# Derive distribution name from module name (agentic_consult -> agentic-consult)
_DIST_NAME = __name__.replace("_", "-")

__version__ = version(_DIST_NAME)
__package_name__ = _DIST_NAME

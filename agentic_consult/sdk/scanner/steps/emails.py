"""Email address checks."""

from typing import List

from agentic_consult.config import load_app_config
from ..utils import CheckResult, run_cmd, DIFF_METADATA_FILTER


# Default acceptable email domains (RFC-reserved fake domains, GitHub noreply)
DEFAULT_ACCEPTABLE_DOMAINS = [
    'example.com', 'example.org', 'example.net', 'test.com',
    'users.noreply.github.com',
]

# Python decorator modules that look like email domains
DECORATOR_MODULES = [
    'click.', 'cli.', 'pytest.', 'mcp.', 'app.', 'flask.',
    'config.', 'profile.', 'settings.', 'router.', 'api.', 'auth.',
    'staticmethod', 'classmethod', 'property', 'dataclass',
    'fixture', 'mark.', 'tool', 'command', 'group', 'option',
]


def get_allowed_emails() -> List[str]:
    """Load allowed emails from config, with defaults."""
    app_config = load_app_config()
    return app_config.get('precommit', {}).get('allowed_emails', [])


def check_emails(repo_path: str) -> CheckResult:
    """Check for email addresses that might be personal."""
    cmd = f"git diff --staged 2>/dev/null | {DIFF_METADATA_FILTER} | grep -oiE '[a-z0-9._%+-]{{2,}}@[a-z0-9.-]+\\.[a-z]{{2,}}' | sort -u | head -20"
    rc, stdout, _ = run_cmd(cmd, repo_path)

    # Load allowed emails from config
    allowed_emails = set(e.lower() for e in get_allowed_emails())

    findings = []
    if stdout.strip():
        for email in stdout.strip().split("\n"):
            email_lower = email.lower().lstrip('+-')

            # Skip if in allowed list
            if email_lower in allowed_emails:
                continue

            # Skip acceptable domains (RFC-reserved, noreply)
            if any(domain in email_lower for domain in DEFAULT_ACCEPTABLE_DOMAINS):
                continue

            # Skip if looks like Python decorator
            at_pos = email_lower.find('@')
            if at_pos >= 0:
                domain_part = email_lower[at_pos + 1:]
                if any(domain_part.startswith(mod) for mod in DECORATOR_MODULES):
                    continue

            findings.append(email)

    passed = len(findings) == 0
    return CheckResult("Email addresses", passed, findings[:10])


def run_checks(repo_path: str, deep: bool = False) -> List[CheckResult]:
    """Run all email checks. Standard step interface."""
    return [check_emails(repo_path)]

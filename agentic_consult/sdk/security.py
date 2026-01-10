from typing import List, Optional
import fnmatch
from agentic_consult.config import load_app_config

def get_allowed_emails(filter_pattern: Optional[str] = None, limit: Optional[int] = None) -> List[str]:
    """
    Retrieves the list of allowed/fake email addresses from configuration.
    Preserves the order defined in app.yaml to prioritize 'best' examples.
    """
    app_config = load_app_config()
    emails = app_config.get('precommit', {}).get('allowed_emails', [])

    if filter_pattern:
        emails = [e for e in emails if fnmatch.fnmatch(e, filter_pattern)]

    if limit:
        emails = emails[:limit]

    return emails

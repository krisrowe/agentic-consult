"""Google Chat triage - temporarily disabled.

Chat functionality requires gwsa SDK which is being removed.
TODO: Implement sdk/chat with direct Google Chat API access.
"""

import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


def get_chat_mentions(
    limit: Optional[int] = None,
    unanswered_only: bool = False,
    tiers: Optional[List[Dict[str, Any]]] = None,
    message_limit: Optional[int] = None,
    verbose: bool = False
) -> Dict[str, Any]:
    """Scans Google Chat for actionable mentions and unread DMs.

    Currently disabled - returns empty result.
    """
    logger.info("Chat triage temporarily disabled (gwsa dependency removed)")
    return {
        "mentions": [],
        "scanned_spaces": 0,
        "total_active_spaces": 0,
        "disabled_reason": "Chat SDK not yet implemented"
    }

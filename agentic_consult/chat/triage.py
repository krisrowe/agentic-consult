import logging
import re
from typing import Dict, Any, Optional, List
from agentic_consult.config import load_app_config
from gwsa.sdk.chat.triage import get_chat_mentions as sdk_get_chat_mentions
from gwsa.sdk.profiles import get_active_profile

logger = logging.getLogger(__name__)

def get_chat_mentions(
    limit: Optional[int] = None, 
    unanswered_only: bool = True,
    tiers: Optional[List[Dict[str, Any]]] = None,
    message_limit: Optional[int] = None,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Scans Google Chat for actionable mentions and unread DMs.
    
    Thin wrapper around gwsa.sdk.chat.triage that adds agentic-consult
    specific disabling logic and configuration mapping.
    """
    config = load_app_config()
    chat_config = config.get('chat', {}).get('triage', {})
    
    if limit is None:
        limit = chat_config.get('limit', 20)
        
    if message_limit is None:
        message_limit = chat_config.get('message_limit', 100)
    
    # 0. Check Disable Pattern (Application-level rule)
    disabled_pattern = chat_config.get('disabled_email_pattern')
    if disabled_pattern:
        try:
            profile = get_active_profile()
            email = profile.get('email', '')
            if re.match(disabled_pattern, email):
                logger.info(f"Chat triage disabled for profile {email}")
                return {
                    "mentions": [],
                    "scanned_spaces": 0,
                    "total_active_spaces": 0,
                    "disabled_reason": f"Profile matches {disabled_pattern}"
                }
        except Exception as e:
            logger.warning(f"Failed to check profile for chat disable: {e}")

    # 1. Delegate to the optimized SDK logic
    # Note: We map SDK return names to match agentic-consult's expectations
    # Use provided tiers or fall back to config
    final_tiers = tiers if tiers is not None else chat_config.get('tiers')
    
    result = sdk_get_chat_mentions(
        limit=limit,
        implicit_mention_threshold=chat_config.get('implicit_mention_threshold', 3),
        tiers=final_tiers,
        unanswered_only=unanswered_only,
        message_limit=message_limit
    )
    
    response = {
        "mentions": result.get("mentions", []),
        "scanned_count": result.get("scanned_count", 0),
        "total_active_spaces": result.get("total_count", 0)
    }
    
    if verbose:
        response["source"] = result.get("source", {})
        response["api_stats"] = result.get("api_stats", {})
        
    return response
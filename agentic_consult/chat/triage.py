import logging
import re
from typing import List, Dict, Any
from datetime import datetime, timedelta, timezone
from agentic_consult.config import load_app_config
from gwsa.sdk.chat import get_chat_service
from gwsa.sdk.people import get_me, get_person_name
from gwsa.sdk.profiles import get_active_profile

logger = logging.getLogger(__name__)

def parse_api_time(timestamp: str) -> datetime:
    """Parses Google API timestamp (RFC 3339) to UTC datetime."""
    if not timestamp:
        return datetime.min.replace(tzinfo=timezone.utc)
    ts = timestamp.replace("Z", "+00:00")
    if "." in ts:
        parts = ts.split(".")
        seconds = parts[1].split("+")
        if len(seconds[0]) > 6:
            ts = f"{parts[0]}.{seconds[0][:6]}+{seconds[1]}"
    return datetime.fromisoformat(ts)

def get_chat_mentions(limit: int = 20) -> Dict[str, Any]:
    """
    Scans Google Chat for actionable mentions and unread DMs.
    """
    config = load_app_config()
    chat_config = config.get('chat', {}).get('triage', {})
    
    # 0. Check Disable Pattern
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

    implicit_threshold = chat_config.get('implicit_mention_threshold', 3)
    tiers = chat_config.get('tiers', [])
    tiers.sort(key=lambda x: float('inf') if x['max_members'] is None else x['max_members'])

    service = get_chat_service()
    
    # Identify myself
    myself = get_me()
    my_id = myself.get('name') # users/123...
    my_display_name = myself.get('displayName', '').split(' ')[0]

    # 1. Fetch Candidate Spaces
    fields = "nextPageToken,spaces(name,displayName,spaceType,lastActiveTime,membershipCount)"
    all_spaces = []
    page_token = None
    
    while True:
        try:
            # Fetch in smaller batches for responsiveness
            res = service.spaces().list(pageSize=100, fields=fields, pageToken=page_token).execute()
            all_spaces.extend(res.get('spaces', []))
            page_token = res.get('nextPageToken')
            if not page_token or len(all_spaces) >= 200: # Depth limit
                break
        except Exception as e:
            logger.error(f"Failed to list spaces: {e}")
            break
            
    # 2. Filter Candidates
    now = datetime.now(timezone.utc)
    candidates = []
    
    for space in all_spaces:
        members_count = 0
        if 'membershipCount' in space:
            members_count = space['membershipCount'].get('joinedDirectHumanUserCount', 2)
        elif space.get('spaceType') == 'DIRECT_MESSAGE':
            members_count = 2
            
        lookback_days = 1
        for tier in tiers:
            limit_members = tier['max_members']
            if limit_members is None or members_count <= limit_members:
                lookback_days = tier['lookback_days']
                break
        
        if lookback_days <= 0:
            continue
            
        last_active = parse_api_time(space.get('lastActiveTime'))
        cutoff = now - timedelta(days=lookback_days)
        
        if last_active > cutoff:
            candidates.append({
                'space': space,
                'members': members_count,
                'last_active': last_active
            })

    candidates.sort(key=lambda x: x['last_active'], reverse=True)
    
    # 3. Analyze Candidates
    results = []
    
    for item in candidates[:limit]:
        space = item['space']
        members = item['members']
        space_name = space['name']
        display_name = space.get('displayName')
        
        # If DM and no display name, resolve other member
        if not display_name or display_name == "Unknown":
            try:
                m_res = service.spaces().members().list(parent=space_name, pageSize=5).execute()
                memberships = m_res.get('memberships', [])
                other_names = []
                for m in memberships:
                    m_id = m.get('member', {}).get('name')
                    if m_id != my_id:
                        other_names.append(get_person_name(m_id))
                if other_names:
                    display_name = ", ".join(other_names)
                else:
                    display_name = f"Group ({members} members)"
            except Exception:
                display_name = "Unknown Space"

        is_implicit = members <= implicit_threshold
        
        try:
            fetch_limit = 1 if is_implicit else 20
            msgs_res = service.spaces().messages().list(
                parent=space_name, 
                pageSize=fetch_limit, 
                orderBy="createTime desc"
            ).execute()
            
            messages = msgs_res.get('messages', [])
            if not messages:
                continue
            
            # Check for "Handled" status (I spoke recently)
            # Since messages are newest-first, if I encounter my own message
            # BEFORE I encounter a mention/activity, I have likely handled it.
            
            i_have_responded = False
            
            for msg in messages:
                sender_id = msg.get('sender', {}).get('name')
                
                if sender_id == my_id:
                    i_have_responded = True
                    continue # Skip checking this message, I sent it
                
                # Check for actionable item
                found_item = None
                
                if is_implicit:
                    # Implicit: Any message not from me is actionable...
                    # UNLESS I have already responded to something newer.
                    if not i_have_responded:
                        found_item = {
                            "type": "DM" if members == 2 else "Small Group",
                            "reason": "Unreplied message"
                        }
                else:
                    # Explicit: Check for @Mention
                    mentioned = False
                    if 'annotations' in msg:
                        for ann in msg['annotations']:
                            if ann.get('type') == 'USER_MENTION':
                                if ann.get('userMention', {}).get('user', {}).get('name') == my_id:
                                    mentioned = True
                                    break
                    if not mentioned and my_display_name and f"@{my_display_name}" in msg.get('text', ''):
                        mentioned = True
                        
                    if mentioned and not i_have_responded:
                        found_item = {
                            "type": "Mention",
                            "reason": "Explicit mention"
                        }
                
                if found_item:
                    results.append({
                        "type": found_item['type'],
                        "space": display_name,
                        "space_id": space_name,
                        "thread_name": msg.get('thread', {}).get('name'),
                        "time": msg.get('createTime'),
                        "sender": msg.get('sender', {}).get('displayName') or "Unknown",
                        "text": msg.get('text', '')[:100],
                        "reason": found_item['reason']
                    })
                    break # Only report the latest actionable item per space

        except Exception as e:
            logger.warning(f"Failed to scan space {space_name}: {e}")
            continue

    return {
        "mentions": results,
        "scanned_spaces": len(candidates),
        "total_active_spaces": len(all_spaces)
    }

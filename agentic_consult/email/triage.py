"""
Email triage SDK - Gemini-powered email processing.

This module provides the core logic for email triage, separate from MCP
to allow direct testing without spinning up a server.
"""

import json
import logging
import os
import re
import textwrap
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Literal, Optional, Union

import yaml

from agentic_consult.config import load_app_config, get_consult_config_dir, get_user_datetime, load_updateable
from agentic_consult.gemini import GeminiAPIClient, GeminiJSONParseError, GeminiJSONExtractionError
from agentic_consult.mcp.email_processing import load_email_rules, get_cache_dir
from agentic_consult.chat.triage import get_chat_mentions

logger = logging.getLogger(__name__)
EMAIL_CACHE_SUBDIR = "emails"
CONTACTS_CONFIG_FILE = "contacts.yaml"
REF_MAP_FILE = "ref_map.json"


def _get_package_dir() -> Path:
    """Get the agentic_consult package directory."""
    return Path(__file__).parent.parent


def _get_email_cache_dir() -> Path:
    """Get email cache directory."""
    cache_dir = get_cache_dir() / EMAIL_CACHE_SUBDIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _load_app_email_config() -> dict:
    """Load email configuration from app.yaml (package defaults)."""
    try:
        config = load_app_config()
        return config.get("email", {})
    except Exception:
        return {}


def _load_user_email_config() -> dict:
    """Load user email configuration from email.yaml."""
    from agentic_consult.mcp.email_processing import get_email_config_path
    path = get_email_config_path()
    if not path.exists():
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _load_contacts_config() -> dict:
    """Load contacts configuration from config dir."""
    path = get_consult_config_dir() / CONTACTS_CONFIG_FILE
    if not path.exists():
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"Failed to load contacts config: {e}")
        return {}


def _format_contacts_context(config: dict) -> str:
    """Format contacts configuration for the prompt."""
    contacts = config.get('contacts', {})
    if not contacts:
        return "No contact context configured."

    lines = []
    customers = contacts.get('customers', [])
    if customers:
        lines.append(f"- **Customers (Domains/Patterns):** {', '.join(customers)}")
    vips = contacts.get('vips', [])
    if vips:
        lines.append(f"- **VIPs (Managers/Leads):** {', '.join(vips)}")
    identity = contacts.get('identity', {})
    emails = identity.get('emails', [])
    names = identity.get('names', [])
    if emails or names:
        parts = []
        if emails: parts.append(f"Emails: {', '.join(emails)}")
        if names: parts.append(f"Names/Nicknames: {', '.join(names)}")
        lines.append(f"- **User Identity:** {'; '.join(parts)}")

    return "\n".join(lines)


def _resolve_config_value(config: dict, path: str) -> str:
    """Resolve a dot-notation path (e.g., 'contacts.auto_archive_lists') in config."""
    current = config
    try:
        for key in path.split('.'):
            current = current.get(key, {})
        
        if isinstance(current, list):
            return ", ".join(str(x) for x in current)
        return str(current)
    except Exception:
        return f"[Missing config: {path}]"

def _inject_config_into_rules(rules: list[dict], config: dict) -> list[dict]:
    """Inject config values into rule conditions using {{path}} syntax."""
    import re
    processed_rules = []
    
    # Matches {{ path.to.value }}
    pattern = re.compile(r'\{\{\s*([\w\.]+)\s*\}\}')
    
    for rule in rules:
        new_rule = rule.copy()
        condition = new_rule.get('condition', '')
        
        def replace_match(match):
            path = match.group(1)
            return _resolve_config_value(config, path)
            
        if pattern.search(condition):
            new_rule['condition'] = pattern.sub(replace_match, condition)
            
        processed_rules.append(new_rule)
    return processed_rules


def load_triage_prompt_template() -> str:
    """Load the Gemini triage prompt template.

    Uses load_updateable() for GCS hot-patch support:
    1. Check $CONSULT_CONFIG_DIR/app/triage_prompt.txt (GCS on Cloud Run)
    2. Fall back to package-bundled template

    See DESIGN.md section 15 for details.
    """
    return load_updateable(Path(__file__).parent / "triage_prompt.txt")


def _get_shortcode_pool() -> list[str]:
    codes = []
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for char in chars:
        for digit in range(10):
            codes.append(f"{char}{digit}")
    return codes


def _load_ref_map() -> dict:
    cache_dir = get_cache_dir()
    map_path = cache_dir / REF_MAP_FILE
    if not map_path.exists():
        return {"next_seq": 1, "refs": {}}
    try:
        with open(map_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if "refs" in data else {"next_seq": 1, "refs": {}}
    except Exception:
        return {"next_seq": 1, "refs": {}}


def _save_ref_map(data: dict) -> None:
    cache_dir = get_cache_dir()
    map_path = cache_dir / REF_MAP_FILE
    with open(map_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def _assign_shortcodes(message_ids: list[str]) -> dict[str, str]:
    data = _load_ref_map()
    refs = data["refs"]
    next_seq = data.get("next_seq", 1)
    id_to_code = {info["id"]: code for code, info in refs.items()}
    assignments = {}
    for msg_id in message_ids:
        if msg_id in id_to_code:
            code = id_to_code[msg_id]
            refs[code]["seq"] = next_seq
            assignments[msg_id] = code
            next_seq += 1
        else:
            pool = set(_get_shortcode_pool())
            used_codes = set(refs.keys())
            available = sorted(list(pool - used_codes))
            if available:
                code = available[0]
                refs[code] = {"id": msg_id, "seq": next_seq}
                assignments[msg_id] = code
                next_seq += 1
            else:
                if refs:
                    lru_code = min(refs, key=lambda k: refs[k]["seq"])
                    refs[lru_code] = {"id": msg_id, "seq": next_seq}
                    assignments[msg_id] = lru_code
                    next_seq += 1
    data["next_seq"] = next_seq
    _save_ref_map(data)
    return assignments

def _cache_filename(message_id: str, email_date: str) -> str:
    safe_id = message_id.replace('/', '_').replace('\\', '_')
    return f"{safe_id}_{email_date}.json"

def cache_email(email: dict) -> Path:
    cache_dir = _get_email_cache_dir()
    message_id = email.get('id', 'unknown')
    email_date = email.get('date', datetime.now().strftime('%Y-%m-%d'))
    if isinstance(email_date, datetime):
        email_date = email_date.strftime('%Y-%m-%d')
    elif len(email_date) > 10:
        email_date = email_date[:10]
    filename = _cache_filename(message_id, email_date)
    cache_path = cache_dir / filename
    cached_email = {**email, 'cached_at': datetime.utcnow().isoformat()}
    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(cached_email, f, indent=2, default=str)
    return cache_path

def get_cached_emails(message_ids: list[str]) -> dict[str, Any]:
    if not message_ids:
        return {'messages': []}
    cache_dir = _get_email_cache_dir()
    messages = []
    for message_id in message_ids:
        safe_id = message_id.replace('/', '_').replace('\\', '_')
        found = False
        for cache_file in cache_dir.glob(f"{safe_id}_*.json"):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    email = json.load(f)
                    result = {'id': message_id}
                    result.update(email)
                    messages.append(result)
                    found = True
                    break
            except Exception:
                messages.append({'id': message_id, 'error': {'code': 'read_error'}})
                found = True
                break
        if not found:
            messages.append({'id': message_id, 'error': {'code': 'not_cached'}})
    return {'messages': messages}

def cleanup_email_cache() -> int:
    cache_dir = _get_email_cache_dir()
    config = _load_app_email_config()
    cache_config = config.get('cache', {})
    file_age_days = cache_config.get('cleanup_file_age_days', 7)
    email_max_age_days = cache_config.get('email_max_age_days', 30)
    now = datetime.now()
    file_age_cutoff = now - timedelta(days=file_age_days)
    email_date_cutoff = now - timedelta(days=email_max_age_days)
    removed_count = 0
    for cache_file in cache_dir.glob("*.json"):
        try:
            file_mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
            if file_mtime >= file_age_cutoff: continue
            parts = cache_file.stem.rsplit('_', 1)
            if len(parts) != 2: continue
            email_date = datetime.strptime(parts[1], '%Y-%m-%d')
            if email_date >= email_date_cutoff: continue
            cache_file.unlink()
            removed_count += 1
        except Exception: pass
    return removed_count

def mark_email_in_review(message_id: str, reverse: bool = False, profile: Optional[str] = None) -> dict[str, Any]:
    from agentic_consult.sdk.gmail import add_label, remove_label
    label = _load_app_email_config().get('review_label', 'Reviewing')
    try:
        if reverse:
            remove_label(message_id, label)
        else:
            add_label(message_id, label)
        return {'success': True, 'message_id': message_id, 'action': 'removed' if reverse else 'applied'}
    except Exception as e:
        return {'success': False, 'message_id': message_id, 'error': str(e)}

def _build_gmail_query(review_status: str) -> str:
    config = _load_app_email_config()
    review_label = config.get('review_label', 'Reviewing')
    if review_status == "new":
        return f"in:inbox -label:{review_label}"
    elif review_status == "reviewing":
        return f"in:inbox label:{review_label}"
    return "in:inbox"

def _prepare_emails_for_prompt(emails: list[dict]) -> str:
    config = _load_app_email_config()
    max_email_chars = config.get('max_email_chars', 100000)
    truncated_emails = []
    for email in emails:
        email_copy = dict(email)
        body = email_copy.get('body', '')
        if len(body) > max_email_chars:
            email_copy['body'] = body[:max_email_chars] + "\n[TRUNCATED]"
        truncated_emails.append(email_copy)
    return json.dumps(truncated_emails, indent=2, default=str)

EXPECTED_ANALYSIS_FREQ_MINS = 30  # Warn if emails lack analysis longer than this


def fetch_triage_pool(
    review_status: Literal["new", "reviewing", "all"] = "all",
    limit: int = 5,
    profile: Optional[str] = None,
    model: Optional[str] = None,
    width: Literal["small", "medium", "large"] = "medium",
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> dict[str, Any]:
    """
    Fetch pool of emails ready for triage.

    Gmail is source of truth for inbox state. EmailStore provides cached analysis.

    Returns:
        Dict containing:
        - emails: List of email recommendations
        - invites: List of calendar invite recommendations
        - chat_mentions: List of chat mentions requiring attention
        - instructions: Agent instructions for processing
        - stats: Counts including gmail_count, analyzed_count, skipped_no_analysis
        - current_datetime: ISO 8601 timestamp with timezone offset
    """
    import time
    from email_archive import EmailStore
    from agentic_consult.sdk.gmail import list_inbox

    messages = []  # User-facing messages with severity
    config = _load_app_email_config()
    review_label = config.get('review_label', 'Reviewing')

    try:
        # 1. Fetch Chat Mentions (optional, can be disabled or fail gracefully)
        chat_mentions = []
        if os.environ.get("TRIAGE_DISABLE_CHAT"):
            logger.info("Chat mentions disabled via TRIAGE_DISABLE_CHAT")
        else:
            try:
                chat_results = get_chat_mentions()
                chat_mentions = chat_results.get('mentions', [])
            except Exception as e:
                logger.warning(f"Failed to retrieve chat mentions: {e}")
                messages.append({
                    "severity": "warning",
                    "text": "Failed to retrieve chat messages."
                })

        # 2. Query Gmail for inbox messages (source of truth)
        gmail_result = list_inbox(
            review_status=review_status,
            review_label=review_label,
            limit=limit * 3  # Fetch extra to account for missing analysis
        )
        gmail_ids = gmail_result.get('message_ids', [])
        gmail_elapsed_ms = gmail_result.get('elapsed_ms', 0)
        logger.debug(f"Gmail query returned {len(gmail_ids)} messages in {gmail_elapsed_ms}ms")

        # 3. Check EmailStore for analysis sidecars
        store = EmailStore()
        store_start = time.time()

        emails = []
        invites = []
        skipped_no_analysis = 0

        for msg_id in gmail_ids:
            if len(emails) + len(invites) >= limit:
                break

            # Must HAVE an analysis sidecar to be shown
            analysis = store.get_sidecar(msg_id, "analysis.json")
            if not analysis:
                skipped_no_analysis += 1
                continue

            # Load raw headers for display
            raw = store.get(msg_id)
            if not raw:
                skipped_no_analysis += 1
                continue

            # Merge for frontend
            item_date = raw.get('date', datetime.utcnow().isoformat())
            entry = {**analysis, "id": msg_id, "date": item_date}
            entry["from"] = raw.get("from", "")
            entry["subject"] = raw.get("subject", "")

            # Split into categories
            if entry.get("status") or "event_date" in entry:
                invites.append(entry)
            else:
                emails.append(entry)

        store_elapsed_ms = int((time.time() - store_start) * 1000)
        logger.debug(f"EmailStore check took {store_elapsed_ms}ms for {len(gmail_ids)} messages")

        # Warn if many emails lack analysis
        if skipped_no_analysis > 0 and len(gmail_ids) > 0:
            skip_ratio = skipped_no_analysis / len(gmail_ids)
            if skip_ratio > 0.5:
                logger.warning(
                    f"{skipped_no_analysis}/{len(gmail_ids)} emails lack analysis. "
                    f"Analyzer may be behind (expected every {EXPECTED_ANALYSIS_FREQ_MINS} mins)."
                )

        # 3. Assign Refs (Same as original logic)
        chat_ids = [m.get('thread_name') or m.get('space_id') for m in chat_mentions]
        email_ids = [e.get('id') for e in emails]
        invite_ids = [i.get('id') for i in invites]
        
        all_ids = chat_ids + email_ids + invite_ids
        assignments = _assign_shortcodes(all_ids)
        
        for m in chat_mentions:
            mid = m.get('thread_name') or m.get('space_id')
            m['ref'] = assignments.get(mid, '??')
            
        for rec in emails:
            rec['ref'] = assignments.get(rec.get('id'), '??')
        for inv in invites:
            inv['ref'] = assignments.get(inv.get('id'), '??')
            
        # 4. Instructions
        instructions = _build_agent_instructions(review_status, emails, invites, width=width, chat_mentions=chat_mentions)

        # 5. Current datetime (reference point for all time-sensitive operations)
        user_dt = get_user_datetime()
        current_datetime = user_dt.isoformat()

        result = {
            'current_datetime': current_datetime,
            'emails': emails,
            'invites': invites,
            'chat_mentions': chat_mentions,
            'instructions': instructions,
            'stats': {
                'email_count': len(emails),
                'invite_count': len(invites),
                'chat_count': len(chat_mentions),
                'gmail_count': len(gmail_ids),
                'skipped_no_analysis': skipped_no_analysis,
                'gmail_elapsed_ms': gmail_elapsed_ms,
                'store_elapsed_ms': store_elapsed_ms
            }
        }
        if messages:
            result['messages'] = messages
        return result
    except Exception as e:
        logger.exception("Error in fetch_triage_pool")
        return {'error': str(e)}

def flag_for_reanalysis(message_ids: list[str]) -> dict[str, Any]:
    """
    Flag emails for reanalysis by removing their analysis.json sidecars.

    The background analyzer job will re-process these emails on its next run.

    Args:
        message_ids: List of message IDs to flag for reanalysis.

    Returns:
        Dict with 'flagged' count and 'errors' list if any failures.
    """
    store = _get_email_store()
    flagged = 0
    errors = []

    for msg_id in message_ids:
        try:
            # Get the meta path to derive the sidecar path
            meta_path, _ = store._get_paths(msg_id)
            sidecar_path = meta_path.parent / f"{meta_path.stem}.analysis.json"

            if sidecar_path.exists():
                sidecar_path.unlink()
                flagged += 1
                logger.info(f"Flagged {msg_id} for reanalysis (removed analysis.json)")
            else:
                logger.debug(f"No analysis.json found for {msg_id}, nothing to remove")
        except ValueError as e:
            # Email not found in store
            errors.append({"id": msg_id, "error": str(e)})
        except Exception as e:
            errors.append({"id": msg_id, "error": str(e)})
            logger.exception(f"Error flagging {msg_id} for reanalysis")

    result = {"flagged": flagged}
    if errors:
        result["errors"] = errors
    return result

def _truncate(text: str, width: int) -> str:
    """Truncate text to width, appending '..' if truncated."""
    if len(text) <= width:
        return text
    return text[:width-2] + ".."

def _build_agent_instructions(
    review_status: str, 
    emails: list[dict], 
    invites: list[dict],
    width: Literal["small", "medium", "large"] = "medium",
    chat_mentions: list[dict] = []
) -> str:
    # 1. Resolve widths from config
    config = _load_app_email_config()
    width_map = config.get("triage_table_widths", {"small": 80, "medium": 120, "large": 160})
    total_width = width_map.get(width, 120)
    
    # ... (Ratio distribution logic same) ...
    w_ref = 6
    w_icon = 4
    w_date = 8
    
    fixed_usage = w_ref + w_icon + w_date + 15 
    remaining = max(10, total_width - fixed_usage)
    
    w_from = max(8, int(remaining * 0.15))
    w_subj = max(15, int(remaining * 0.30))
    w_rule = max(8, int(remaining * 0.15))
    w_reason = max(15, int(remaining * 0.40))

    grouped = {}
    for rec in emails:
        action = rec.get('recommended_action', 'unknown')
        if action not in grouped: grouped[action] = []
        grouped[action].append(rec)
        
    lines = [
        "## Triage Suggestions",
        "",
        f"**Context:** Rule-based suggestions for your review. (Table width: {width}/{total_width})",
        ""
    ]

    # --- Chat Section ---
    if chat_mentions:
        lines.append("### 💬 Google Chat Recent Mentions & DMs")
        lines.append("| Ref | Type | Space | Date | From | Message Preview | Reason |")
        lines.append("|:---|:---|:---|:---|:---|:---|:---|")
        
        for m in chat_mentions:
            ref = m.get('ref', '??')
            m_type = m.get('type', 'Chat')
            space = _truncate(m.get('space', 'Unknown'), 20)
            
            raw_time = m.get('time', '')
            date_disp = _format_short_date(raw_time) if raw_time else "??"
            
            sender = _truncate(m.get('sender', 'Unknown'), 15)
            text = _truncate(m.get('text', '').replace('\n', ' '), 40)
            reason = m.get('reason', 'Mentioned')
            
            lines.append(f"| **{ref}** | {m_type} | {space} | {date_disp} | {sender} | {text} | {reason} |")
        lines.append("")
    
    # --- Invites Section ---
    if invites:
        lines.append(f"### 📅 Calendar Invites ({len(invites)})")
        lines.append("_Agent: Check your calendar for these times. Show availability status (✅/❌) in the 'Avail' column._")
        # Invites table format is different, keeping simple fixed for now or could apply similar logic
        lines.append("| Ref | Avail | Status | Date | Event | Sender | Subject | VIP |")
        lines.append("|:---|:---|:---|:---|:---|:---|:---|:---|")
        
        for inv in invites:
            ref = inv.get('ref', '??')
            avail = "❓" # Placeholder for agent to fill
            status = inv.get('status', 'PROPOSED')
            status_icon = "🆕" if status == 'PROPOSED' else "📌"
            
            raw_date = inv.get('date', '')
            date_disp = _format_short_date(raw_date)
            
            event_date = str(inv.get('event_date') or 'See details')[:20]
            sender = _format_sender(inv.get('from', ''))
            subj = _format_subject(inv.get('subject', ''))
            vip = inv.get('vip_status', 'EXTERNAL')
            vip_icon = "⭐" if vip in ['VIP', 'CUSTOMER'] else "👤"
            
            lines.append(f"| **{ref}** | {avail} | {status_icon} | {date_disp} | {event_date} | {sender} | {subj} | {vip_icon} |")
        lines.append("")
    
    cmd_map = {
        'review': 'do rev',
        'track_as_task': 'do task',
        'archive': 'do arc',
        'ask_user': 'do rev'
    }

    display_order = ['review', 'track_as_task', 'ask_user', 'archive']
    
    for action in display_order:
        if action in grouped and grouped[action]:
            recs = grouped[action]
            lines.append(f"### Action: `{action}` ({len(recs)})")
            
            # Header
            # Using manual spacing in header to hint at widths is hard in MD, just standard MD table
            lines.append("| Ref | | Date | From | Subject | Rule | Reason |")
            lines.append("|:---|:---|:---|:---|:---|:---|:---|")
            
            month_map = {
                "01": "JA", "02": "FE", "03": "MR", "04": "AP",
                "05": "MY", "06": "JN", "07": "JL", "08": "AU",
                "09": "SE", "10": "OC", "11": "NV", "12": "DE"
            }
            
            audience_map = {
                "DIRECT": "👤",
                "GROUP": "👥", 
                "MENTION": "🔔",
                "BROADCAST": "📢"
            }
            
            for rec in recs:
                ref = rec.get('ref', '??')
                icon = audience_map.get(rec.get('audience', 'BROADCAST'), "📢")
                
                raw_date = rec.get('date', '')
                if len(raw_date) >= 10:
                    try:
                        dt = datetime.strptime(raw_date[:10], '%Y-%m-%d')
                        # MTWRFSU mapping (R=Thu, U=Sun)
                        day_code = ["M", "T", "W", "R", "F", "S", "U"][dt.weekday()]
                        mm = raw_date[5:7]
                        dd = raw_date[8:10]
                        date = f"{day_code} {dd}{month_map.get(mm, '??')}"
                    except Exception:
                        date = "??"
                else:
                    date = "??"
                
                # Truncate fields based on calculated widths
                raw_sender = str(rec.get('from') or '').split('<')[0].strip()
                sender = _truncate(raw_sender, w_from)
                
                raw_subj = str(rec.get('subject') or '').replace('|', '-').replace('\n', ' ')
                subj = _truncate(raw_subj, w_subj)
                
                rule_id = str(rec.get('rule_id') or '-')
                raw_rule = re.sub(r'^[a-z]{3,4}-', '', rule_id)
                rule_disp = _truncate(raw_rule, w_rule)
                
                raw_reason = rec.get('reason', 'No reason provided').replace('\n', ' ')
                reason = _truncate(raw_reason, w_reason)
                
                lines.append(f"| **{ref}** | {icon} | {date} | {sender} | {subj} | `{rule_disp}` | {reason} |")
            lines.append("") # Spacer
                
    lines.append("\n## Suggested Actions (Copy/Paste Block)\n```bash")
    
    # Invites commands
    if invites:
        inv_refs = [i.get('ref') for i in invites]
        lines.append(f"# Invites: Check calendar, then: do accept {' '.join(inv_refs)}")
    
    for action in display_order:
        if action in grouped and grouped[action]:
             cmd = cmd_map.get(action)
             if cmd:
                 # Group by rule_id to provide context
                 by_rule = {}
                 for r in grouped[action]:
                     rule = r.get('rule_id') or "ad-hoc"
                     if rule not in by_rule: by_rule[rule] = []
                     by_rule[rule].append(r['ref'])
                 
                 for rule, refs in by_rule.items():
                     lines.append(f"{cmd} {' '.join(refs)} # {rule}")
                     
    lines.append("```")
    
    # Brief guidance - the docstring teaches the full workflow, this just reminds
    lines.append("\n**Response options:** `agree` | `agree except do rev A1` | `do <cmd> <refs>` | other guidance")
    
    return "\n".join(lines)

# Missing helpers from original file that I need to keep/restore
def _format_short_date(raw_date: str) -> str:
    """Format date as 'W 21JA' (weekday + day + 2-char month). 6 chars."""
    month_map = {
        "01": "JA", "02": "FE", "03": "MR", "04": "AP",
        "05": "MY", "06": "JN", "07": "JL", "08": "AU",
        "09": "SE", "10": "OC", "11": "NV", "12": "DE"
    }
    if len(raw_date) >= 10:
        try:
            dt = datetime.strptime(raw_date[:10], '%Y-%m-%d')
            day_code = ["M", "T", "W", "R", "F", "S", "U"][dt.weekday()]
            mm = raw_date[5:7]
            dd = raw_date[8:10]
            return f"{day_code} {dd}{month_map.get(mm, '??')}"
        except Exception:
            return "??"
    return "??"


def format_display_date(email_date: datetime, now: datetime = None) -> str:
    """
    Format email date for display in triage table. Always 6 chars.

    - < 24 hours ago: "10:03A" or " 9:15P" (time with A/P suffix)
    - Yesterday: "Yester"
    - Older: "W 21JA" (weekday + day + 2-char month)

    Args:
        email_date: The email's datetime (should be timezone-aware or naive UTC)
        now: Current datetime for comparison (defaults to utcnow)

    Returns:
        6-character display string
    """
    from agentic_consult.config import get_user_datetime

    if now is None:
        now = get_user_datetime()

    # Make both naive for comparison if needed
    if email_date.tzinfo is not None and now.tzinfo is None:
        email_date = email_date.replace(tzinfo=None)
    elif email_date.tzinfo is None and now.tzinfo is not None:
        now = now.replace(tzinfo=None)

    # Calculate time difference
    diff = now - email_date
    hours_ago = diff.total_seconds() / 3600

    # < 24 hours: show time "10:03A" or " 9:15P"
    if hours_ago < 24:
        hour = email_date.hour
        minute = email_date.minute
        am_pm = "A" if hour < 12 else "P"
        hour_12 = hour % 12
        if hour_12 == 0:
            hour_12 = 12
        # Pad to 6 chars: " 9:15P" or "10:03A"
        return f"{hour_12:2d}:{minute:02d}{am_pm}"

    # Yesterday check (same calendar day - 1)
    email_day = email_date.date()
    now_day = now.date()
    if (now_day - email_day).days == 1:
        return "Yester"

    # Older: use W 21JA format
    month_map = {
        1: "JA", 2: "FE", 3: "MR", 4: "AP",
        5: "MY", 6: "JN", 7: "JL", 8: "AU",
        9: "SE", 10: "OC", 11: "NV", 12: "DE"
    }
    day_code = ["M", "T", "W", "R", "F", "S", "U"][email_date.weekday()]
    dd = email_date.day
    month_abbr = month_map.get(email_date.month, "??")
    return f"{day_code} {dd:02d}{month_abbr}"

def _format_sender(sender: str) -> str:
    return str(sender).split('<')[0].strip()[:12]

def _format_subject(subject: str) -> str:
    return str(subject)[:20].replace('|', '-').replace('\n', ' ')


def get_triage_stats(sample_size: int = 20) -> dict:
    """
    Get email triage statistics.

    Gmail is source of truth for inbox state. EmailStore tracks fetched/analyzed.

    Args:
        sample_size: Max emails to load for action breakdown (default 20).

    Returns:
        {
            "emails": {
                "fetched": {"count": N, "start": "YYYY-MM-DD HH:MM", "end": "..."},
                "analyzed": {"count": N, "start": "...", "end": "..."},
                "active": {"count": N, "sample": {...}}  # In inbox with analysis
            }
        }
    """
    from email_archive import EmailStore
    from agentic_consult.sdk.gmail import list_inbox

    store = EmailStore()

    if not store.root.exists():
        return {"error": "Email archive directory not found", "path": str(store.root)}

    def format_date(dt: Optional[datetime]) -> Optional[str]:
        if dt is None:
            return None
        return dt.strftime("%Y-%m-%d %I:%M %p")

    def get_date_range(items: list) -> tuple:
        """Extract min/max dates from list of items with 'date' field."""
        dates = []
        for item in items:
            dt = item.get('date')
            if dt is not None:
                if isinstance(dt, datetime):
                    dates.append(dt)
                elif isinstance(dt, str):
                    try:
                        dates.append(datetime.fromisoformat(dt.replace('Z', '+00:00')))
                    except (ValueError, TypeError):
                        pass
        if not dates:
            return None, None
        return min(dates), max(dates)

    # Fetched = all emails in store
    all_emails = store.list()
    fetched_start, fetched_end = get_date_range(all_emails)
    fetched = {
        "count": len(all_emails),
        "start": format_date(fetched_start),
        "end": format_date(fetched_end)
    }

    # Analyzed = has analysis.json in store
    analyzed_ids = set()
    for item in all_emails:
        msg_id = item.get('id')
        if msg_id and store.has_sidecar(msg_id, "analysis.json"):
            analyzed_ids.add(msg_id)

    analyzed_items = [e for e in all_emails if e.get('id') in analyzed_ids]
    analyzed_start, analyzed_end = get_date_range(analyzed_items)
    analyzed = {
        "count": len(analyzed_ids),
        "start": format_date(analyzed_start),
        "end": format_date(analyzed_end)
    }

    # Active = currently in Gmail inbox AND has analysis
    # Query Gmail for current inbox state (source of truth)
    gmail_result = list_inbox(review_status="all", limit=500)
    inbox_ids = set(gmail_result.get('message_ids', []))

    active_ids = analyzed_ids & inbox_ids  # Intersection: analyzed AND in inbox
    active_items = [e for e in all_emails if e.get('id') in active_ids]
    active_start, active_end = get_date_range(active_items)
    active_result = {
        "count": len(active_ids),
        "start": format_date(active_start),
        "end": format_date(active_end)
    }

    # Sample active emails to break down by (action, rule_id) pairs
    if active_ids and sample_size > 0:
        sample_ids = list(active_ids)[:sample_size]
        by_action_rule: dict[str, dict[str, int]] = {}
        loaded = 0

        for msg_id in sample_ids:
            analysis = store.get_sidecar(msg_id, "analysis.json")
            if analysis:
                action = analysis.get("recommended_action", "unknown")
                rule_id = analysis.get("rule_id") or "unmatched"
                if action not in by_action_rule:
                    by_action_rule[action] = {}
                by_action_rule[action][rule_id] = by_action_rule[action].get(rule_id, 0) + 1
                loaded += 1

        active_result["sample"] = {
            "size": loaded,
            **by_action_rule
        }

    return {
        "emails": {
            "fetched": fetched,
            "analyzed": analyzed,
            "active": active_result
        }
    }
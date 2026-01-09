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

from agentic_consult.config import load_app_config, get_consult_config_dir
from agentic_consult.gemini import GeminiAPIClient, GeminiJSONParseError, GeminiJSONExtractionError
from agentic_consult.mcp.email_processing import load_email_rules, get_cache_dir
from agentic_consult.chat.triage import get_chat_mentions

logger = logging.getLogger(__name__)

TRIAGE_TEMPLATE_FILE = "templates/email_triage.txt"
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


def load_triage_template() -> str:
    """Load the Gemini triage prompt template."""
    template_path = _get_package_dir() / TRIAGE_TEMPLATE_FILE
    if not template_path.exists():
        raise FileNotFoundError(f"Triage template not found: {template_path}")
    return template_path.read_text(encoding='utf-8')


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
    from gwsa.sdk.mail.label import add_label, remove_label
    label = _load_app_email_config().get('review_label', 'Reviewing')
    try:
        if reverse:
            remove_label(message_id, label, profile=profile)
        else:
            add_label(message_id, label, profile=profile)
        return {'success': True, 'message_id': message_id, 'action': 'removed' if reverse else 'applied'}
    except Exception as e:
        return {'success': False, 'message_id': message_id, 'error': str(e)}

def mark_email_archivable(message_id: str, reverse: bool = False, profile: Optional[str] = None) -> dict[str, Any]:
    from gwsa.sdk.mail.label import add_label, remove_label
    label = _load_app_email_config().get('archivable_label', 'Archivable')
    try:
        if reverse:
            remove_label(message_id, label, profile=profile)
        else:
            add_label(message_id, label, profile=profile)
        return {'success': True, 'message_id': message_id, 'action': 'removed' if reverse else 'applied'}
    except Exception as e:
        return {'success': False, 'message_id': message_id, 'error': str(e)}

def _build_gmail_query(review_status: str) -> str:
    config = _load_app_email_config()
    review_label = config.get('review_label', 'Reviewing')
    archivable_label = config.get('archivable_label', 'Archivable')
    if review_status == "new":
        return f"in:inbox -label:{review_label} -label:{archivable_label}"
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

def triage_emails(
    review_status: Literal["new", "reviewing", "all"] = "all",
    limit: int = 5,
    profile: Optional[str] = None,
    model: Optional[str] = None,
    width: Literal["small", "medium", "large"] = "medium",
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> dict[str, Any]:
    try:
        # 1. Fetch Chat Mentions/DMs
        chat_results = get_chat_mentions()
        chat_mentions = chat_results.get('mentions', [])

        # 2. Fetch Emails
        query = _build_gmail_query(review_status)
        if progress_callback: progress_callback(1, 2)
        from gwsa.sdk.mail.search import search_messages
        messages, _metadata = search_messages(query=query, max_results=limit, format="metadata", profile=profile)
        message_ids = [m['id'] for m in messages]
        
        if not message_ids:
            instructions = _build_agent_instructions(review_status, [], [], width=width, chat_mentions=chat_mentions)
            return {
                'emails': [], 
                'invites': [], 
                'chat_mentions': chat_mentions,
                'rules_referenced': [], 
                'instructions': instructions, 
                'stats': {'email_count': 0, 'chat_count': len(chat_mentions)}
            }
        
        if progress_callback: progress_callback(2, 2)
        
        result = analyze_emails(message_ids, profile=profile, model=model)
        if 'error' in result: return result
        
        emails = result.get('emails', [])
        invites = result.get('invites', [])
        
        # Assign Refs to all items
        chat_ids = [m.get('thread_name') or m.get('space_id') for m in chat_mentions]
        email_ids = [e.get('id') for e in emails]
        invite_ids = [i.get('id') for i in invites]
        
        all_ids = chat_ids + email_ids + invite_ids
        assignments = _assign_shortcodes(all_ids)
        
        for m in chat_mentions:
            mid = m.get('thread_name') or m.get('space_id')
            m['ref'] = assignments.get(mid, '??')
            
        for rec in emails:
            msg_id = rec.get('id')
            rec['ref'] = assignments.get(msg_id, '??')
        for inv in invites:
            msg_id = inv.get('id')
            inv['ref'] = assignments.get(msg_id, '??')
            
        all_rules = load_email_rules()
        active_rules = [r for r in all_rules if not r.get('disabled', False)]
        referenced_rule_ids = {r.get('rule_id') for r in emails if r.get('rule_id')}
        rules_referenced = [r for r in active_rules if r.get('id') in referenced_rule_ids]
        
        # Prepend chat info to instructions
        instructions = _build_agent_instructions(review_status, emails, invites, width=width, chat_mentions=chat_mentions)
        
        return {
            'emails': emails,
            'invites': invites,
            'chat_mentions': chat_mentions,
            'rules_referenced': rules_referenced,
            'instructions': instructions,
            'stats': {
                'email_count': len(message_ids),
                'recommendation_count': len(emails),
                'invite_count': len(invites),
                'chat_count': len(chat_mentions),
                'rules_loaded': len(active_rules),
                'rules_matched': len(rules_referenced)
            }
        }
    except Exception as e:
        logger.exception("Error in triage_emails")
        return {'error': str(e)}

def suggest_email_action(message_id: str, profile: Optional[str] = None, model: Optional[str] = None) -> dict[str, Any]:
    try:
        result = analyze_emails([message_id], profile=profile, model=model)
        if 'error' in result: return result
        
        recs = result.get('emails', [])
        invites = result.get('invites', [])
        
        if recs: return recs[0]
        if invites: return invites[0]
        return {'result': 'no_recommendation'}
    except Exception as e:
        logger.exception("Error in suggest_email_action")
        return {'error': str(e)}

def analyze_emails(message_ids: list[str], profile: Optional[str] = None, model: Optional[str] = None) -> dict[str, Any]:
    """
    Unified analysis pipeline: Fetch (Batched) -> Cache -> Load Rules -> Call Gemini.
    """
    try:
        from gwsa.sdk.mail.read import read_messages
        emails = []
        cleanup_email_cache()
        
        # 1. Fetch Full Content for all IDs using efficient batching
        full_messages = read_messages(message_ids, profile=profile)
        
        for msg in full_messages:
            email = {
                'id': msg['id'],
                'date': msg.get('date', ''),
                'from': msg.get('from', ''),
                'to': msg.get('to', ''),
                'subject': msg.get('subject', ''),
                'body': msg.get('body', {}).get('text') or msg.get('body', {}).get('html') or '',
                'labels': msg.get('labelIds', [])
            }
            emails.append(email)
            cache_email(email)

        if not emails: return []

        # 2. Load Rules & Context
        all_rules = load_email_rules()
        raw_active_rules = [r for r in all_rules if not r.get('disabled', False)]
        
        # Load full contacts config for injection
        contacts_config = _load_contacts_config()
        contacts_context = _format_contacts_context(contacts_config)
        
        # Inject dynamic config values into rules
        active_rules = _inject_config_into_rules(raw_active_rules, contacts_config)
        
        # 3. Build Prompt
        prompt = load_triage_template().format(
            rules_json=json.dumps(active_rules, indent=2),
            emails_json=_prepare_emails_for_prompt(emails),
            contacts_context=contacts_context
        )
        
        # 4. Call Gemini (or Mock)
        user_config = _load_user_email_config()
        if user_config.get('use_mock_gemini', False):
            mock_file = _get_email_cache_dir() / 'mock-triage-response.json'
            if mock_file.exists():
                with open(mock_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return {'emails': data.get('emails', []), 'invites': data.get('invites', [])}
            return {'emails': [], 'invites': []}
            
        client = GeminiAPIClient(model_name=model)
        result = client.generate_prompt_driven_json(prompt)
        
        recs = result.get('emails', [])
        invites = result.get('invites', [])
        
        return {'emails': recs, 'invites': invites}
    except Exception as e:
        logger.error(f"Analysis Failed: {e}")
        return {'error': str(e)}

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
        'archive_now': 'do arc',
        'archive_later': 'do later',
        'ask_user': 'do rev' 
    }

    display_order = ['review', 'track_as_task', 'ask_user', 'archive_now', 'archive_later']
    
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
    
    lines.append("\n**Agent Instructions:**")
    lines.append("1. **Display the Table:** You MUST present the table above exactly as shown, but FILL IN the 'Avail' column for invites.")
    lines.append("   - Check your calendar for the 'Event' times.")
    lines.append("   - Replace ❓ with ✅ (Free) or ❌ (Conflict).")
    lines.append("2. **Execute Commands:**")
    lines.append("   - `do accept <refs>` -> (Agent Logic) Check calendar -> Create Event -> Reply to email -> Archive.")
    lines.append("   - `do rev <refs>` -> Call `mark_email_in_review(message_id=...)`")
    lines.append("   - `do task <refs>` -> Create task, then `archive_email(message_id=...)`")
    lines.append("   - `do arc <refs>` -> Call `archive_email(message_id=..., reason='ad-hoc')`")
    lines.append("   - `do later <refs>` -> Call `mark_email_archivable(message_id=...)`")
    lines.append("   - `do sum <refs>` -> Call `get_cached_emails(message_ids=[...])` and summarize")
    lines.append("   - `do show <refs>` -> Call `get_cached_emails(message_ids=[...])` and display full content")
    lines.append("   - `do relist` -> Redisplay table with only unprocessed items from this batch")
    lines.append("3. **Loop:** After executing actions, check if inbox is empty. If not, call `triage_emails(review_status='new')` to fetch the next batch.")
    
    return "\n".join(lines)

# Missing helpers from original file that I need to keep/restore
def _format_short_date(raw_date: str) -> str:
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

def _format_sender(sender: str) -> str:
    return str(sender).split('<')[0].strip()[:12]

def _format_subject(subject: str) -> str:
    return str(subject)[:20].replace('|', '-').replace('\n', ' ')
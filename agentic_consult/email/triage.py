"""
Email triage SDK - Gemini-powered email processing.

This module provides the core logic for email triage, separate from MCP
to allow direct testing without spinning up a server.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Literal, Optional

import yaml

from agentic_consult.config import load_app_config, get_consult_config_dir
from agentic_consult.gemini import GeminiAPIClient, GeminiJSONParseError, GeminiJSONExtractionError
from agentic_consult.mcp.email_processing import load_email_rules, get_cache_dir

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
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> dict[str, Any]:
    try:
        query = _build_gmail_query(review_status)
        if progress_callback: progress_callback(1, 2)
        from gwsa.sdk.mail.search import search_messages
        messages, _metadata = search_messages(query=query, max_results=limit, format="metadata", profile=profile)
        message_ids = [m['id'] for m in messages]
        if not message_ids:
            return {'recommendations': [], 'rules_referenced': [], 'instructions': "No emails found.", 'stats': {'email_count': 0}}
        if progress_callback: progress_callback(2, 2)
        
        recommendations = analyze_emails(message_ids, profile=profile, model=model)
        if isinstance(recommendations, dict) and 'error' in recommendations: return recommendations
        
        assignments = _assign_shortcodes(message_ids)
        for rec in recommendations:
            msg_id = rec.get('id')
            rec['ref'] = assignments.get(msg_id, '??')
            
        all_rules = load_email_rules()
        active_rules = [r for r in all_rules if not r.get('disabled', False)]
        referenced_rule_ids = {r.get('rule_id') for r in recommendations if r.get('rule_id')}
        rules_referenced = [r for r in active_rules if r.get('id') in referenced_rule_ids]
        instructions = _build_agent_instructions(review_status, recommendations)
        
        return {
            'recommendations': recommendations,
            'rules_referenced': rules_referenced,
            'instructions': instructions,
            'stats': {
                'email_count': len(message_ids),
                'recommendation_count': len(recommendations),
                'rules_loaded': len(active_rules),
                'rules_matched': len(rules_referenced)
            }
        }
    except Exception as e:
        logger.exception("Error in triage_emails")
        return {'error': str(e)}

def suggest_email_action(message_id: str, profile: Optional[str] = None, model: Optional[str] = None) -> dict[str, Any]:
    try:
        recommendations = analyze_emails([message_id], profile=profile, model=model)
        if isinstance(recommendations, dict) and 'error' in recommendations: return recommendations
        if not recommendations: return {'result': 'no_recommendation'}
        return recommendations[0]
    except Exception as e:
        logger.exception("Error in suggest_email_action")
        return {'error': str(e)}

def analyze_emails(message_ids: list[str], profile: Optional[str] = None, model: Optional[str] = None) -> list[dict]:
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
        active_rules = [r for r in all_rules if not r.get('disabled', False)]
        contacts_context = _format_contacts_context(_load_contacts_config())
        
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
                    return json.load(f).get('recommendations', [])
            return []
            
        client = GeminiAPIClient(model_name=model)
        result = client.generate_prompt_driven_json(prompt)
        
        # Ensure ID is attached to recommendations if Gemini missed it
        recs = result.get('recommendations', [])
        if len(recs) == len(emails):
            for i, rec in enumerate(recs):
                if not rec.get('id'): rec['id'] = emails[i]['id']
        return recs
    except Exception as e:
        logger.error(f"Analysis Failed: {e}")
        return {'error': str(e)}

def _build_agent_instructions(review_status: str, recommendations: list[dict]) -> str:
    grouped = {}
    for rec in recommendations:
        action = rec.get('recommended_action', 'unknown')
        if action not in grouped: grouped[action] = []
        grouped[action].append(rec)
        
    lines = [
        "## Triage Suggestions",
        "",
        "**Context:** Rule-based suggestions for your review.",
        ""
    ]
    
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
            lines.append("| Ref | Date | From | Subject | Rule | Reason |")
            lines.append("|:---|:---|:---|:---|:---|:---|")
            
            for rec in recs:
                ref = rec.get('ref', '??')
                date = rec.get('date', '')[5:10] # MM-DD
                sender = rec.get('from', '').split('<')[0].strip()[:20]
                subj = rec.get('subject', '')[:40].replace('|', '-')
                rule_id = rec.get('rule_id', '-')
                reason = rec.get('reason', 'No reason provided')
                
                lines.append(f"| **{ref}** | {date} | {sender} | {subj} | `{rule_id}` | {reason} |")
            lines.append("") # Spacer
                
    lines.append("\n## Suggested Actions (Copy/Paste Block)\n```bash")
    for action in display_order:
        if action in grouped and grouped[action]:
             cmd = cmd_map.get(action)
             if cmd:
                 refs = [r['ref'] for r in grouped[action]]
                 lines.append(f"{cmd} {' '.join(refs)}")
    lines.append("```")
    
    lines.append("\n**Agent Instructions:**")
    lines.append("To execute these commands:")
    lines.append("1. `do rev <refs>` -> Call `mark_email_in_review(message_id=...)` for each ref.")
    lines.append("2. `do task <refs>` -> Create task, then `archive_email(message_id=...)`.")
    lines.append("3. `do arc <refs>` -> Call `archive_email(message_id=..., reason='ad-hoc')`.")
    lines.append("4. `do later <refs>` -> Call `mark_email_archivable(message_id=...)`.")
    
    return "\n".join(lines)
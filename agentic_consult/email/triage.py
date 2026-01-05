"""
Email triage SDK - Gemini-powered email processing.

This module provides the core logic for email triage, separate from MCP
to allow direct testing without spinning up a server.

## Architecture

1. Fetch emails from Gmail based on review_status filter
2. Cache emails locally for efficient retrieval
3. Load rules (unified system + user rules from MCP loader)
4. Call Gemini with emails + rules + prompt template
5. Return structured recommendations

## State Machine

Emails transition through states via Gmail labels:
- [Inbox, No Label] → Initial state
- [Inbox, Reviewing] → Needs human attention
- [Archived] → Removed from inbox
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
    """
    Load user email configuration from email.yaml (CONSULT_CONFIG_DIR).

    This is where test flags like use_mock_emails/use_mock_gemini go,
    since CONSULT_CONFIG_DIR can be overridden via env var for testing.
    """
    from agentic_consult.mcp.email_processing import get_email_config_path
    import yaml

    path = get_email_config_path()
    if not path.exists():
        return {}

    try:
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def load_triage_template() -> str:
    """Load the Gemini triage prompt template."""
    template_path = _get_package_dir() / TRIAGE_TEMPLATE_FILE
    if not template_path.exists():
        raise FileNotFoundError(f"Triage template not found: {template_path}")

    return template_path.read_text(encoding='utf-8')


# -----------------------------------------------------------------------------
# Email Caching
# -----------------------------------------------------------------------------

def _cache_filename(message_id: str, email_date: str) -> str:
    """Generate cache filename from message ID and date."""
    # Sanitize message_id for filesystem
    safe_id = message_id.replace('/', '_').replace('\\', '_')
    return f"{safe_id}_{email_date}.json"


def cache_email(email: dict) -> Path:
    """
    Cache an email to the local cache directory.

    Args:
        email: Email dict with id, date, from, subject, body, etc.

    Returns:
        Path to the cached file.
    """
    cache_dir = _get_email_cache_dir()

    message_id = email.get('id', 'unknown')
    # Extract date, default to today if not present
    email_date = email.get('date', datetime.now().strftime('%Y-%m-%d'))
    if isinstance(email_date, datetime):
        email_date = email_date.strftime('%Y-%m-%d')
    elif len(email_date) > 10:
        # Truncate datetime strings to just date
        email_date = email_date[:10]

    filename = _cache_filename(message_id, email_date)
    cache_path = cache_dir / filename

    # Add caching metadata
    cached_email = {
        **email,
        'cached_at': datetime.utcnow().isoformat()
    }

    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(cached_email, f, indent=2, default=str)

    return cache_path


def get_cached_emails(message_ids: list[str]) -> dict[str, Any]:
    """
    Retrieve multiple cached emails by message IDs.

    Args:
        message_ids: List of Gmail message IDs (minimum 1)

    Returns:
        Dict with 'messages' array. Each item has 'id' at top level, then either:
            - The email fields (from, subject, body, cached_at, etc.)
            - An 'error' object with {code, message}

        Check for 'error' field to detect failures; absence means success.

        Error codes:
            - "not_cached": Email not found in cache
            - "read_error": Failed to read cache file
    """
    if not message_ids:
        return {'messages': []}

    cache_dir = _get_email_cache_dir()
    messages = []

    for message_id in message_ids:
        # Sanitize for matching
        safe_id = message_id.replace('/', '_').replace('\\', '_')

        # Find matching file (message_id is prefix before the date)
        found = False
        for cache_file in cache_dir.glob(f"{safe_id}_*.json"):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    email = json.load(f)
                    # Flatten: id at top level, rest of email fields alongside
                    result = {'id': message_id}
                    result.update(email)
                    messages.append(result)
                    found = True
                    break
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to read cached email {cache_file}: {e}")
                messages.append({
                    'id': message_id,
                    'error': {
                        'code': 'read_error',
                        'message': f"Failed to read cache: {e}"
                    }
                })
                found = True  # Don't also add not_cached
                break

        if not found:
            messages.append({
                'id': message_id,
                'error': {
                    'code': 'not_cached',
                    'message': "Not in cache. Use gwsa read_email to fetch."
                }
            })

    return {'messages': messages}


def cleanup_email_cache() -> int:
    """
    Clean up old cached emails based on configured retention.

    Cleanup criteria - delete file if BOTH:
    1. File creation date >= cleanup_file_age_days old
    2. Email date (from filename) >= email_max_age_days old

    Returns:
        Number of files removed.
    """
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
            # Check file age (creation/modification time)
            file_mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
            if file_mtime >= file_age_cutoff:
                # File is too recent, skip
                continue

            # Extract email date from filename (format: {id}_{YYYY-MM-DD}.json)
            parts = cache_file.stem.rsplit('_', 1)
            if len(parts) != 2:
                continue

            try:
                email_date = datetime.strptime(parts[1], '%Y-%m-%d')
            except ValueError:
                continue

            if email_date >= email_date_cutoff:
                # Email is too recent, skip
                continue

            # Both criteria met, delete
            cache_file.unlink()
            removed_count += 1
            logger.debug(f"Cleaned up cached email: {cache_file.name}")

        except Exception as e:
            logger.warning(f"Failed to process cache file {cache_file}: {e}")

    if removed_count > 0:
        logger.info(f"Cleaned up {removed_count} cached emails")

    return removed_count


# -----------------------------------------------------------------------------
# Email Review State Management
# -----------------------------------------------------------------------------

def get_review_label() -> str:
    """Get the Gmail label used for emails needing review."""
    config = _load_app_email_config()
    return config.get('review_label', 'Reviewing')


def get_archivable_label() -> str:
    """Get the Gmail label used for emails pending age-based archive."""
    config = _load_app_email_config()
    return config.get('archivable_label', 'Archivable')


def mark_email_in_review(
    message_id: str,
    reverse: bool = False,
    profile: Optional[str] = None
) -> dict[str, Any]:
    """
    Apply or remove the Reviewing label from an email.

    Args:
        message_id: Gmail message ID
        reverse: If True, remove the label instead of adding
        profile: Optional gwsa profile

    Returns:
        Dict with success status
    """
    from gwsa.sdk.mail.label import add_label as gwsa_add_label
    from gwsa.sdk.mail.label import remove_label as gwsa_remove_label

    label = get_review_label()

    try:
        if reverse:
            gwsa_remove_label(message_id, label, profile=profile)
            action = "removed"
        else:
            gwsa_add_label(message_id, label, profile=profile)
            action = "applied"

        return {
            'success': True,
            'message_id': message_id,
            'label': label,
            'action': action
        }
    except Exception as e:
        return {
            'success': False,
            'message_id': message_id,
            'error': str(e)
        }


def mark_email_archivable(
    message_id: str,
    reverse: bool = False,
    profile: Optional[str] = None
) -> dict[str, Any]:
    """
    Apply or remove the Archivable label from an email.

    Args:
        message_id: Gmail message ID
        reverse: If True, remove the label instead of adding
        profile: Optional gwsa profile

    Returns:
        Dict with success status
    """
    from gwsa.sdk.mail.label import add_label as gwsa_add_label
    from gwsa.sdk.mail.label import remove_label as gwsa_remove_label

    label = get_archivable_label()

    try:
        if reverse:
            gwsa_remove_label(message_id, label, profile=profile)
        else:
            gwsa_add_label(message_id, label, profile=profile)

        return {
            'success': True,
            'message_id': message_id,
            'label': label,
            'action': 'removed' if reverse else 'applied'
        }
    except Exception as e:
        return {
            'success': False,
            'message_id': message_id,
            'error': str(e)
        }


# -----------------------------------------------------------------------------
# Main Triage Function
# -----------------------------------------------------------------------------

def _build_gmail_query(review_status: str) -> str:
    """Build Gmail query based on review status filter."""
    review_label = get_review_label()
    archivable_label = get_archivable_label()

    if review_status == "new":
        # Exclude both Reviewing and Archivable labels
        return f"in:inbox -label:{review_label} -label:{archivable_label}"
    elif review_status == "reviewing":
        return f"in:inbox label:{review_label}"
    else:  # "all"
        return "in:inbox"


def _fetch_emails(
    query: str,
    limit: int,
    profile: Optional[str] = None
) -> list[dict]:
    """
    Fetch emails from Gmail using gwsa, or from mock file if configured.

    Returns list of email dicts with full content.

    For testing: Set email.use_mock_emails: true in config, then place
    mock-triage-emails.json in the cache directory.
    """
    user_config = _load_user_email_config()

    # Check for mock mode (from user config, controllable via CONSULT_CONFIG_DIR)
    if user_config.get('use_mock_emails', False):
        mock_file = _get_email_cache_dir() / 'mock-triage-emails.json'
        if mock_file.exists():
            logger.info(f"Using mock emails from {mock_file}")
            with open(mock_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            logger.warning(f"use_mock_emails=true but {mock_file} not found")
            return []

    from gwsa.sdk.mail.search import search_messages

    # search_messages returns tuple: (list of message dicts, metadata dict)
    # With format="full", messages already include body, snippet, attachments
    messages, _metadata = search_messages(
        query=query,
        max_results=limit,
        format="full",
        profile=profile
    )

    # Transform to our expected format
    emails = []
    for msg in messages:
        email = {
            'id': msg.get('id'),
            'date': msg.get('date', ''),
            'from': msg.get('from', ''),
            'to': msg.get('to', ''),
            'subject': msg.get('subject', ''),
            'body': msg.get('body', ''),
            'labels': msg.get('labelIds', [])
        }
        emails.append(email)

    return emails


def _prepare_emails_for_prompt(emails: list[dict]) -> str:
    """Format emails as JSON for the Gemini prompt."""
    config = _load_app_email_config()
    max_email_chars = config.get('max_email_chars', 100000)

    # Truncate individual emails if needed
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
    limit: int = 20,
    profile: Optional[str] = None,
    model: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> dict[str, Any]:
    """
    Triage inbox emails using Gemini.

    This is the main SDK function that:
    1. Fetches emails based on review_status filter
    2. Caches each email locally
    3. Loads rules (unified from MCP loader)
    4. Calls Gemini with emails + rules + template
    5. Returns structured recommendations

    Args:
        review_status: Filter emails by state
            - "new": Emails in inbox without Reviewing label
            - "reviewing": Emails with Reviewing label
            - "all": All inbox emails
        limit: Maximum emails to fetch (default 20)
        profile: Optional gwsa profile name
        model: Optional Gemini model override

    For testing: Set CONSULT_CONFIG_DIR and XDG_CACHE_HOME to temp dirs, then:
        - In email.yaml: use_mock_emails: true, use_mock_gemini: true
        - In cache dir: mock-triage-emails.json, mock-triage-response.json

    Returns:
        Dict with:
            - recommendations: List of email recommendations from Gemini
            - rules_referenced: Rules that were mentioned in recommendations
            - instructions: Guidance for the agent on next steps
            - stats: Processing statistics
    """
    try:
        # Step 1: Build query and fetch emails
        query = _build_gmail_query(review_status)
        logger.info(f"Fetching emails with query: {query}")

        if progress_callback:
            progress_callback(1, 2)  # Step 1/2: Fetching emails

        emails = _fetch_emails(query, limit, profile)

        if not emails:
            return {
                'recommendations': [],
                'rules_referenced': [],
                'instructions': "No emails found matching the filter.",
                'stats': {'email_count': 0}
            }

        # Step 2: Cache each email (triggers cleanup as side effect)
        cleanup_email_cache()  # Best-effort cleanup before caching
        for email in emails:
            cache_email(email)

        # Step 3: Load and filter rules (NEW: Use unified loader)
        all_rules = load_email_rules()
        # Filter disabled rules
        active_rules = [r for r in all_rules if not r.get('disabled', False)]

        # Step 4: Build prompt
        template = load_triage_template()
        emails_json = _prepare_emails_for_prompt(emails)
        rules_json = json.dumps(active_rules, indent=2)

        prompt = template.format(
            rules_json=rules_json,
            emails_json=emails_json
        )

        # Step 5: Call Gemini (or use mock response)
        if progress_callback:
            progress_callback(2, 2)  # Step 2/2: Calling Gemini

        user_config = _load_user_email_config()

        if user_config.get('use_mock_gemini', False):
            mock_file = _get_email_cache_dir() / 'mock-triage-response.json'
            if mock_file.exists():
                logger.info(f"Using mock Gemini response from {mock_file}")
                with open(mock_file, 'r', encoding='utf-8') as f:
                    result = json.load(f)
            else:
                logger.warning(f"use_mock_gemini=true but {mock_file} not found")
                result = {'recommendations': []}
        else:
            try:
                client = GeminiAPIClient(model_name=model)
            except ValueError as e:
                # Diagnostic for API key issues
                import os
                gemini_keys = {k: len(v) for k, v in os.environ.items() if 'GEMINI' in k.upper()}
                return {
                    'error': f"{e}. Env vars with GEMINI: {gemini_keys}",
                    'stats': {'email_count': len(emails)}
                }
            try:
                result = client.generate_prompt_driven_json(prompt)
            except (GeminiJSONParseError, GeminiJSONExtractionError) as e:
                logger.error(f"Failed to parse Gemini response: {e}")
                return {
                    'error': f"Gemini returned invalid JSON: {e}",
                    'stats': {'email_count': len(emails)}
                }

        recommendations = result.get('recommendations', [])

        # Step 6: Extract referenced rules
        referenced_rule_ids = set()
        for rec in recommendations:
            rule_id = rec.get('rule_id')
            if rule_id:
                referenced_rule_ids.add(rule_id)

        rules_referenced = [r for r in active_rules if r.get('id') in referenced_rule_ids]

        # Step 8: Build instructions for the agent
        instructions = _build_agent_instructions(review_status, recommendations)

        return {
            'recommendations': recommendations,
            'rules_referenced': rules_referenced,
            'instructions': instructions,
            'stats': {
                'email_count': len(emails),
                'recommendation_count': len(recommendations),
                'rules_loaded': len(active_rules),
                'rules_matched': len(rules_referenced)
            }
        }

    except Exception as e:
        logger.exception("Error in triage_emails")
        return {'error': str(e)}


def _build_agent_instructions(review_status: str, recommendations: list[dict]) -> str:
    """Build instructions for the agent based on triage results."""

    # Count by action
    action_counts = {}
    for rec in recommendations:
        action = rec.get('recommended_action', 'unknown')
        action_counts[action] = action_counts.get(action, 0) + 1

    lines = [
        "## Triage Results",
        "",
        f"Processed {len(recommendations)} emails.",
        ""
    ]

    if action_counts:
        lines.append("**Actions breakdown:**")
        for action, count in sorted(action_counts.items()):
            lines.append(f"- {action}: {count}")
        lines.append("")

    lines.extend([
        "## Next Steps",
        "",
        "1. **Review recommendations** with the user before taking action",
        "2. For `archive_now` recommendations: use `archive_email` tool",
        "3. For `archive_later` recommendations: use `mark_email_archivable` tool",
        "4. For `track_as_task` recommendations: check for existing task, create if needed, then archive",
        "5. For `review` recommendations: use `mark_email_in_review` to apply Reviewing label",
        "6. For `ask_user` recommendations: present to user for decision",
        "",
        "**Available tools:**",
        "- `get_cached_emails([message_ids])`: Get full email content from cache (batch)",
        "- `archive_email(...)`: Archive and log the action",
        "- `mark_email_archivable(message_id)`: Apply Archivable label",
        "- `mark_email_in_review(message_id, reverse=False)`: Apply/remove Reviewing label",
        ""
    ])

    if review_status == "new":
        lines.append("Continue with `triage_emails(review_status='new')` until inbox is triaged.")

    return "\n".join(lines)
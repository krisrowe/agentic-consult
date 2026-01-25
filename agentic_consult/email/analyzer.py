"""
Email Analyzer Service - Asynchronous LLM processing for emails.

Processes raw emails from an EmailStore and persists analysis 
results as sidecar JSON files.
"""

import json
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from email_archive import EmailStore
from agentic_consult.gemini import GeminiAPIClient
from agentic_consult.mcp.email_processing import load_email_rules
from agentic_consult.config import get_user_datetime, get_user_timezone

# Shared Triage Helpers
from .triage import (
    load_triage_prompt_template,
    _load_contacts_config,
    _format_contacts_context,
    _inject_config_into_rules,
    _prepare_emails_for_prompt,
    format_display_date
)

logger = logging.getLogger(__name__)

class AnalysisProvider(Protocol):
    """Abstraction for the inference engine."""
    def analyze(self, email: Dict[str, Any], prompt: str) -> Dict[str, Any]:
        """Takes one email and a prompt, returns one recommendation object."""
        ...

class GeminiProvider:
    """Production provider using the Gemini API."""
    def __init__(self, model: Optional[str] = None):
        self.client = GeminiAPIClient(model_name=model)
    
    def analyze(self, email: Dict[str, Any], prompt: str) -> Dict[str, Any]:
        msg_id = email.get('id', 'unknown')
        logger.debug(f"Analyzing email {msg_id} - sending to Gemini")

        # 1. Invoke Gemini
        response = self.client.generate_prompt_driven_json(prompt)

        logger.debug(f"Gemini returned for {msg_id}: {response}")

        # 2. Flatten the response (Gemini template returns lists)
        recs = response.get("emails", []) + response.get("invites", [])

        if not recs:
            raise RuntimeError(f"No analysis returned for email {msg_id}")

        # 3. Return the specific result for this item
        return recs[0]

class EmailAnalyzer:
    """
    Orchestrates the analysis of emails one-by-one.
    """
    DEFAULT_LOOKBACK = 14
    DEFAULT_LIMIT = 10

    def __init__(self, store: EmailStore, provider: Optional[AnalysisProvider] = None):
        self.store = store
        self.provider = provider or GeminiProvider()

    def process_queue(self, lookback_days: Optional[int] = None, limit: Optional[int] = None, reference_date: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Finds pending emails and processes them individually.
        """
        # SDK-level defaults
        lookback = lookback_days if lookback_days is not None else self.DEFAULT_LOOKBACK
        batch_limit = limit if limit is not None else self.DEFAULT_LIMIT

        # Get user's timezone for date calculations
        timezone = get_user_timezone()
        user_now = reference_date or get_user_datetime()

        # Compute date range in user's timezone
        end_date = user_now.strftime("%Y-%m-%d")
        start_date = (user_now - timedelta(days=lookback)).strftime("%Y-%m-%d")

        # Discovery using high-performance SDK method (Newest first)
        pending = self.store.list(
            start_date=start_date,
            end_date=end_date,
            timezone=timezone,
            sidecar_missing="analysis.json",
            limit=batch_limit,
            newest_first=True
        )
        
        if not pending:
            logger.info(f"Analyzer: Cycle idle. (Window: {lookback}d, Pending: 0)")
            return {"processed": 0, "status": "idle"}

        logger.info(f"Analyzer: Cycle started. (Found: {len(pending)} emails, Limit: {batch_limit})")
        
        success_count = 0
        for i, item in enumerate(pending, 1):
            try:
                # Individual item logging for cloud visibility
                logger.info(f"Analyzer: Processing email {i} of {len(pending)} ({item['id']})")
                self._process_item(item['id'])
                success_count += 1
            except Exception as e:
                logger.error(f"Analyzer: Failed to process {item['id']}: {e}")

        logger.info(f"Analyzer: Cycle completed. (Processed: {success_count}/{len(pending)})")
        return {
            "processed": success_count,
            "status": "completed"
        }

    def _process_item(self, msg_id: str):
        """Loads data for one item and runs the analysis."""
        # 1. Load full email data from SDK
        email_data = self.store.get(msg_id, include_content=True)
        if not email_data:
            raise ValueError(f"Email {msg_id} not found in store.")

        # 2. Build Triage Context
        all_rules = load_email_rules()
        raw_active_rules = [r for r in all_rules if not r.get('disabled', False)]
        contacts_config = _load_contacts_config()
        contacts_context = _format_contacts_context(contacts_config)
        active_rules = _inject_config_into_rules(raw_active_rules, contacts_config)

        # 3. Build Single-Email Prompt
        # Use whichever body is larger (HTML usually contains more info for bills/statements)
        body_text = email_data.get("body_text") or ""
        body_html = email_data.get("body_html") or ""
        body = body_html if len(body_html) > len(body_text) else body_text
        if not body:
            body = email_data.get("snippet", "")

        email_payload = [{
            "id": email_data["id"],
            "date": email_data["date"],
            "from": email_data["from"],
            "to": email_data.get("to", ""),
            "subject": email_data["subject"],
            "body": body,
            "labels": email_data.get("labels", [])
        }]

        prompt = load_triage_prompt_template().format(
            rules_json=json.dumps(active_rules, indent=2),
            emails_json=_prepare_emails_for_prompt(email_payload),
            contacts_context=contacts_context,
            user_datetime=get_user_datetime().strftime("%Y-%m-%d %H:%M:%S %Z").strip()
        )

        # 4. Invoke Provider
        # Parse email date (handles both RFC 2822 and ISO 8601 formats)
        def parse_email_date(date_str):
            """Parse date from RFC 2822 or ISO 8601 format."""
            from email.utils import parsedate_to_datetime
            # Try RFC 2822 first (e.g., "Tue, 21 Jan 2026 13:00:00 -0600")
            try:
                return parsedate_to_datetime(date_str)
            except Exception:
                pass
            # Try ISO 8601 (e.g., "2026-01-21T13:00:00")
            try:
                return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            except Exception:
                pass
            return None

        email_dt = parse_email_date(email_data["date"])
        if email_dt:
            email_date_str = email_dt.strftime("%Y-%m-%d %I:%M %p")
        else:
            email_date_str = email_data["date"]
        logger.info(f"Asking Gemini (via API) about message {msg_id} from {email_date_str}...")
        result = self.provider.analyze(email_payload[0], prompt)

        # 5. Compute display_date (SDK responsibility, not Gemini)
        if email_dt:
            result["display_date"] = format_display_date(email_dt)
        else:
            result["display_date"] = "??"

        # 6. Save Sidecar via SDK
        self.store.save_sidecar(msg_id, "analysis.json", result)

        # 6. Structured logging for metrics/debugging
        from agentic_consult.logging import log_json

        action = result.get("action", "unknown")
        rule_id = result.get("rule_id", result.get("rule", "none"))
        reason = result.get("reason", "")

        # INFO: Summary for metrics
        info_payload = {
            "event": "analysis_complete",
            "msg_id": msg_id,
            "email_date": email_data["date"],
            "action": action,
            "rule": rule_id,
            "reason": reason
        }
        # Note: These fields may contain PII when enabled
        if os.environ.get("INFO_LOG_EMAIL_SUBJECT", "").lower() in ("true", "1", "yes"):
            info_payload["subject"] = email_data["subject"]
        if os.environ.get("INFO_LOG_EMAIL_SENDER", "").lower() in ("true", "1", "yes"):
            info_payload["from"] = email_data["from"]
        log_json("INFO", info_payload)

        # DEBUG: Full context for debugging
        log_json("DEBUG", {
            "event": "analysis_detail",
            "email": {
                "id": msg_id,
                "date": email_data["date"],
                "from": email_data["from"],
                "subject": email_data["subject"]
            },
            "analysis": result
        })


def reset_analysis(target_date: date) -> Dict[str, Any]:
    """Reset analysis sidecars for emails on a specific date.

    Clears analysis.json sidecars so emails will be re-analyzed with current prompt.
    Uses timezone from user's email.yaml config.

    Args:
        target_date: Date to reset (date object or "YYYY-MM-DD" string)

    Returns:
        {
            "success": true,
            "count": N,          # Number of sidecars removed
            "first": "datetime", # Earliest email (ISO 8601, user's timezone), null if none
            "last": "datetime"   # Latest email (ISO 8601, user's timezone), null if none
        }
    """
    timezone = get_user_timezone()
    date_str = target_date.isoformat() if hasattr(target_date, 'isoformat') else str(target_date)

    store = EmailStore()
    return store.clear_sidecars("analysis.json", date_str, date_str, timezone)

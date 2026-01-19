"""
Structured logging utilities for GCP Cloud Logging.

GCP Cloud Logging parses raw JSON from stdout/stderr as structured logs.
This module provides helpers to emit properly formatted JSON logs that
Cloud Logging will parse (not escape as strings).

Usage:
    from agentic_consult.logging import log_json, log_feature_notice

    log_json("INFO", {
        "event": "analysis_complete",
        "msg_id": "abc123",
        "action": "archive"
    })

    log_feature_notice(
        "INFO_LOG_EMAIL_SUBJECT",
        "email subjects will be logged (may contain PII)",
        "EMAIL_PII_LOG_NOTICE"
    )
"""

import json
import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, Optional


def log_json(
    level: str,
    payload: Dict[str, Any],
    message: Optional[str] = None
) -> None:
    """
    Emit a structured JSON log entry for GCP Cloud Logging.

    Args:
        level: Log level ("DEBUG", "INFO", "WARNING", "ERROR")
        payload: Dict to include in the log entry (will be JSON-serialized)
        message: Optional message field (defaults to "structured_log")

    The output format follows GCP's structured logging spec:
    https://cloud.google.com/logging/docs/structured-logging
    """
    # Check if this level should be logged
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    if not root_logger.isEnabledFor(numeric_level):
        return

    # Build the structured log entry
    entry = {
        "severity": level.upper(),
        "message": message or "structured_log",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        **payload
    }

    # Output raw JSON to stdout - Cloud Logging will parse it
    print(json.dumps(entry, default=str), file=sys.stdout, flush=True)


def log_feature_notice(
    feature_env_var: str,
    message: str,
    level_env_var: str,
    default_level: str = "WARNING"
) -> None:
    """
    Log a notice if a feature is enabled, at a configurable level.

    Args:
        feature_env_var: Env var that enables the feature (e.g., "INFO_LOG_EMAIL_SUBJECT")
        message: The notice message
        level_env_var: Env var to control notice level (e.g., "EMAIL_PII_LOG_NOTICE")
        default_level: Default log level if env var not set (default: "WARNING")

    The level_env_var accepts: DEBUG, INFO, WARNING, ERROR, CRITICAL, or NONE (to disable)
    """
    # Check if the feature is enabled
    if os.environ.get(feature_env_var, "").lower() not in ("true", "1", "yes"):
        return

    # Get the configured log level
    log_level = os.environ.get(level_env_var, default_level).upper()

    # Log the notice at the configured level (unless NONE)
    if log_level != "NONE":
        level = getattr(logging, log_level, logging.WARNING)
        logging.log(level, f"{feature_env_var}=true: {message}")

    # Always log debug hint about how to control this
    logging.debug(f"Control notice level with {level_env_var}=WARNING|INFO|DEBUG|ERROR|NONE")

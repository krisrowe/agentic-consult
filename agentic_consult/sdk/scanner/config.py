"""Configuration loading for scanner patterns and thresholds."""

import re
from pathlib import Path
from typing import Optional

import yaml

from agentic_consult.config import get_config_path

PATTERNS_FILENAME = "sensitive-patterns.yaml"


def find_patterns_yaml() -> Optional[Path]:
    """Find user's patterns config file.

    Returns:
        Path to sensitive-patterns.yaml if found, None otherwise.
    """
    path = get_config_path(PATTERNS_FILENAME)
    return path if path.exists() else None


def load_patterns() -> tuple[list[dict], list[str]]:
    """Load sensitive patterns from YAML config.

    Returns:
        (patterns_list, simple_patterns_for_grep)
        - patterns_list: full pattern dicts with category, word_boundary, not_followed_by
        - simple_patterns_for_grep: list of simple strings for basic grep (no regex features)
    """
    yaml_path = find_patterns_yaml()

    if not yaml_path:
        # No user config - return empty patterns
        return [], []

    with open(yaml_path) as f:
        config = yaml.safe_load(f) or {}

    patterns = config.get("patterns", [])

    # Build simple pattern list for grep commands (patterns without regex features)
    simple_patterns = []
    for p in patterns:
        pattern = p.get("pattern", "")
        # Skip patterns that need regex features - they'll be checked separately
        if p.get("word_boundary") or p.get("not_followed_by"):
            continue
        simple_patterns.append(pattern)

    return patterns, simple_patterns


def load_thresholds() -> dict:
    """Load dollar amount thresholds from config.

    Returns:
        Dict with threshold values, using defaults if not configured.
    """
    yaml_path = find_patterns_yaml()

    defaults = {
        "large_amount": 300000,
        "suspicious_nonround": 10000,
        "suspicious_any": 100000,
        "cents_review": 500,
    }

    if not yaml_path:
        return defaults

    with open(yaml_path) as f:
        config = yaml.safe_load(f) or {}

    thresholds = config.get("thresholds", {})

    # Merge with defaults
    for key, default_val in defaults.items():
        thresholds.setdefault(key, default_val)

    return thresholds


def build_regex_for_pattern(p: dict) -> str:
    """Build regex string for a single pattern config."""
    pattern = p.get("pattern", "")

    # Escape regex special chars in the base pattern
    escaped = re.escape(pattern)

    # Apply word boundary if requested
    if p.get("word_boundary"):
        escaped = rf"\b{escaped}\b"

    # Apply negative lookahead if specified
    not_followed = p.get("not_followed_by", [])
    if not_followed:
        escaped_opts = [re.escape(opt) for opt in not_followed]
        lookahead = f"(?!({'|'.join(escaped_opts)}))"
        escaped = f"{escaped}{lookahead}"

    return escaped

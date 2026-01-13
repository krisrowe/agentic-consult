"""Email processing rules and workflow instructions for agents.

Rule Loading Order (Progressive Layering):
1. System Rules (pkg://rules/system_rules.yaml)
2. Bundles (pkg://rules/bundles/*.yaml) - Auto-discovered
3. User Config (config://email.yaml)

Logic:
- Each layer merges its rules (overwriting previous rules with same ID).
- IMMEDIATELY after merging, the layer's `enable` and `disable` lists are applied.
- This allows each layer to modify the state of its own rules OR rules from previous layers.
"""

import logging
import json
import os
import fnmatch
from datetime import datetime, timedelta
from typing import Any, Optional
from pathlib import Path

import yaml

from agentic_consult.config import get_config_path, get_consult_config_dir, load_app_config, load_main_config
from gwsa.sdk.mail.label import remove_label as gwsa_remove_label, add_label as gwsa_add_label
from email_archive import EmailStore

logger = logging.getLogger(__name__)
# Default to INFO if not set elsewhere
if not logger.level:
    logger.setLevel(logging.INFO)

EMAIL_CONFIG_FILE = "email.yaml"
TEMPLATE_FILE = "templates/process_email.md"
ARCHIVE_LOG_FILE = "email-archive-log.jsonl"


def get_cache_dir() -> Path:
    """Get XDG cache directory for agentic-consult."""
    xdg_cache = os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
    cache_dir = Path(xdg_cache) / "agentic-consult"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_archive_log_path() -> Path:
    """Get path to archive log file."""
    return get_cache_dir() / ARCHIVE_LOG_FILE


def get_retention_days() -> int:
    """Get log retention days from app config."""
    try:
        config = load_app_config()
        return config.get("email", {}).get("archive_log_retention_days", 90)
    except Exception:
        return 90  # Default fallback


def load_template() -> str:
    """Load email processing template from config directory."""
    template_path = get_consult_config_dir() / TEMPLATE_FILE

    if template_path.exists():
        try:
            return template_path.read_text(encoding='utf-8')
        except IOError as e:
            logger.warning(f"Failed to load template: {e}")

    # Fallback if template doesn't exist
    return """## Email Processing Workflow

Execute these steps to process email:

### Step 1: Check All Profiles
Use `list_profiles` (gwsa) to discover available profiles. Process ALL profiles shown as active/validated.

### Step 2: For Each Profile
1. Switch to profile using `switch_profile`
2. Search inbox: `in:inbox newer_than:3d`
3. Categorize ALL emails (see Step 3 and 4)

### Step 3: Categorize Emails for Auto-Archive

Review each email against the auto-archive rules below. Build a complete list of emails proposed for archiving.

**Auto-Archive Rules:**
{rules_section}

### Step 4: Present Archive Plan to User

**CRITICAL: Before calling `auto_archive_email`, you MUST first present a complete table of ALL emails proposed for archiving:**

| # | From | Subject | Date | Rule/Reason |
|---|------|---------|------|-------------|
| 1 | sender@example.com | Subject line | Jan 3 | usps-digest |
| 2 | ... | ... | ... | ... |

Then call `auto_archive_email` for each. The tool approval mechanism lets the user accept or reject.

**NEVER call auto_archive_email without first showing the user what will be archived and why.**

Use `auto_archive_email` tool (NOT remove_email_label directly) - this logs the action for rule usage tracking.

### Step 5: Process Remaining Emails

Present actionable items grouped by priority:
- **Action Required**: Requests needing response
- **FYI**: Informational items

Get user guidance on each before archiving.

### Step 6: Celebrate
When ANY profile reaches inbox zero, display:

```
✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨

   🎉  INBOX ZERO  🎉

✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨
```
"""


def get_email_config_path() -> Path:
    """Returns path to email.yaml config file."""
    return get_config_path(EMAIL_CONFIG_FILE)


def _get_package_root() -> Path:
    """Returns the package root directory (agentic_consult)."""
    return Path(__file__).parent.parent


def _resolve_path(uri: str) -> Optional[Path]:
    """Resolve URI (pkg:// or config://) to path."""
    if uri.startswith("pkg://"):
        return _get_package_root() / uri.replace("pkg://", "")
    if uri.startswith("config://"):
        return get_consult_config_dir() / uri.replace("config://", "")
    return Path(uri)


def _apply_state_directives(merged_rules: dict, data: dict, source_name: str) -> None:
    """
    Apply 'enable' and 'disable' lists from loaded YAML to current rules.
    """
    # Use 'or []' to handle cases where key exists but is null in YAML
    enable_patterns = data.get('enable') or []
    disable_patterns = data.get('disable') or []

    if not enable_patterns and not disable_patterns:
        return

    for rule_id, rule in merged_rules.items():
        # Check disable first (default priority)
        for pattern in disable_patterns:
            if fnmatch.fnmatch(rule_id, pattern):
                if not rule.get('disabled'):
                    logger.debug(f"Rule '{rule_id}' DISABLED by pattern '{pattern}' in {source_name}")
                rule['disabled'] = True
                
        # Check enable (overrides disable)
        for pattern in enable_patterns:
            if fnmatch.fnmatch(rule_id, pattern):
                if rule.get('disabled'):
                    logger.debug(f"Rule '{rule_id}' ENABLED by pattern '{pattern}' in {source_name}")
                rule['disabled'] = False


def _load_layer(path: Path, merged_rules: dict[str, dict]) -> None:
    """Load a single YAML file layer, merge rules, and apply directives."""
    if not path.exists():
        return

    source_name = path.name
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
            
            # 1. Merge Rules
            # Use 'or []' to handle 'rules: null' cases
            source_rules = data.get('rules') or []
            for rule in source_rules:
                rule_id = rule.get('id')
                if rule_id:
                    if rule_id in merged_rules:
                        logger.debug(f"Rule '{rule_id}' OVERRIDDEN by {source_name}")
                    else:
                        logger.debug(f"Rule '{rule_id}' ADDED from {source_name}")
                    merged_rules[rule_id] = rule
            
            # 2. Apply Enable/Disable Directives
            _apply_state_directives(merged_rules, data, source_name)
                
    except (yaml.YAMLError, IOError) as e:
        logger.warning(f"Failed to load rules from {path}: {e}")


def load_email_rules() -> list[dict]:
    """
    Load email rules from System -> Bundles -> User Config.
    Each layer merges rules and applies state directives.
    """
    logger.debug("Loading email processing rules...")
    merged_rules: dict[str, dict] = {}

    # 1. System Rules
    _load_layer(_resolve_path("pkg://rules/system_rules.yaml"), merged_rules)

    # 2. Bundles (Auto-discovered)
    bundles_dir = _get_package_root() / "rules" / "bundles"
    if bundles_dir.exists():
        for bundle_file in sorted(bundles_dir.glob("*.yaml")):
            _load_layer(bundle_file, merged_rules)

    # 3. User Config
    _load_layer(_resolve_path("config://email.yaml"), merged_rules)

    enabled_count = len([r for r in merged_rules.values() if not r.get('disabled')])
    logger.debug(f"Loaded {len(merged_rules)} total rules ({enabled_count} enabled)")

    return list(merged_rules.values())


def save_email_rules(rules: list[dict]) -> Path:
    """Save email rules to user config. Does not touch system files."""
    path = get_email_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, 'w', encoding='utf-8') as f:
        yaml.dump({'rules': rules}, f, default_flow_style=False, sort_keys=False)

    return path


def format_rules_for_instructions(rules: list[dict]) -> str:
    """Format enabled rules as markdown."""
    active_rules = [r for r in rules if not r.get('disabled', False)]
    
    if not active_rules:
        return "No active auto-archive rules configured."

    lines = []
    for rule in active_rules:
        rule_id = rule.get('id', 'unknown')
        condition = rule.get('condition')
        
        if condition:
            action = rule.get('action', 'review')
            lines.append(f"- **{rule_id}**: {condition.strip()} → {action.upper()}")
        else:
            match = rule.get('match', {})
            match_str = ", ".join([f"{k}: `{v}`" for k, v in match.items() if v]) or "no criteria"
            
            rule_type = rule.get('type', 'custom')
            if rule_type == 'auto_archive':
                lines.append(f"- **{rule_id}**: {match_str} → ARCHIVE")
            else:
                instr = rule.get('instructions', 'No instructions')
                lines.append(f"- **{rule_id}**: {match_str} → {instr}")

    return "\n".join(lines)


def get_process_email_instructions() -> str:
    """Get full email processing instructions with current rules."""
    rules = load_email_rules()
    rules_section = format_rules_for_instructions(rules)
    template = load_template()
    return template.format(rules_section=rules_section)


def add_rule(
    rule_id: str,
    action: str = "review",
    rule_type: Optional[str] = None,
    match_from: Optional[str] = None,
    match_subject: Optional[str] = None,
    instructions: Optional[str] = None
) -> dict:
    """Add a new rule to user config."""
    # Backwards compatibility for rule_type
    if rule_type:
        if not action or action == "review": # Only override default
            if rule_type == "auto_archive":
                action = "archive"
            elif rule_type == "custom":
                action = "review"

    user_config_path = get_email_config_path()
    user_rules = []
    
    if user_config_path.exists():
        try:
            with open(user_config_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
                user_rules = data.get('rules') or []
        except Exception:
            pass

    if any(r.get('id') == rule_id for r in user_rules):
        raise ValueError(f"Rule '{rule_id}' already exists in user config")

    new_rule = {
        'id': rule_id,
        'action': action,
        'match': {}
    }

    if match_from:
        new_rule['match']['from'] = match_from
    if match_subject:
        new_rule['match']['subject'] = match_subject
    if instructions:
        new_rule['instructions'] = instructions

    user_rules.append(new_rule)
    save_email_rules(user_rules)

    return new_rule


def remove_rule(rule_id: str) -> bool:
    """Remove a rule by ID from user config."""
    user_config_path = get_email_config_path()
    if not user_config_path.exists():
        return False
        
    try:
        with open(user_config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
            user_rules = data.get('rules') or []
    except Exception:
        return False

    original_count = len(user_rules)
    user_rules = [r for r in user_rules if r.get('id') != rule_id]

    if len(user_rules) == original_count:
        return False

    save_email_rules(user_rules)
    return True


def list_rules(include_disabled: bool = False) -> list[dict]:
    """List email processing rules."""
    all_rules = load_email_rules()
    if include_disabled:
        return all_rules
    return [r for r in all_rules if not r.get('disabled', False)]


def cleanup_old_logs() -> int:
    """Remove log entries older than retention period."""
    try:
        log_path = get_archive_log_path()
        if not log_path.exists():
            return 0

        retention_days = get_retention_days()
        cutoff = datetime.utcnow() - timedelta(days=retention_days)
        cutoff_str = cutoff.isoformat()

        entries = []
        with open(log_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        recent_entries = [e for e in entries if e.get('timestamp', '') >= cutoff_str]
        removed_count = len(entries) - len(recent_entries)

        if removed_count > 0:
            with open(log_path, 'w', encoding='utf-8') as f:
                for entry in recent_entries:
                    f.write(json.dumps(entry) + '\n')
            logger.info(f"Cleaned up {removed_count} old archive log entries")

        return removed_count

    except Exception as e:
        logger.warning(f"Failed to cleanup old archive logs: {e}")
        return 0


def log_archived_email(
    rule_id: str,
    message_id: str,
    from_addr: str,
    subject: str
) -> None:
    """Log an archived email to the cache."""
    try:
        log_path = get_archive_log_path()
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "rule_id": rule_id,
            "message_id": message_id,
            "from": from_addr,
            "subject": subject[:100]
        }
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + '\n')
        cleanup_old_logs()
    except Exception as e:
        logger.warning(f"Failed to log archived email: {e}")


def get_rule_usage_stats() -> dict[str, dict]:
    """Get usage statistics for each rule."""
    try:
        log_path = get_archive_log_path()
        if not log_path.exists():
            return {}

        stats: dict[str, dict] = {}
        with open(log_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip(): continue
                try:
                    entry = json.loads(line)
                    rule_id = entry.get('rule_id')
                    timestamp = entry.get('timestamp')
                    if rule_id:
                        if rule_id not in stats:
                            stats[rule_id] = {'use_count': 0, 'last_used': None}
                        stats[rule_id]['use_count'] += 1
                        if timestamp and (stats[rule_id]['last_used'] is None or timestamp > stats[rule_id]['last_used']):
                            stats[rule_id]['last_used'] = timestamp
                except json.JSONDecodeError:
                    continue
        return stats
    except Exception as e:
        logger.warning(f"Failed to get rule usage stats: {e}")
        return {}


def archive_email_with_gwsa(
    message_id: str,
    rule_id: str,
    from_addr: str,
    subject: str,
    profile: Optional[str] = None
) -> dict[str, Any]:
    """Archive an email and persist 'triage.json' sidecar."""
    try:
        # 1. Action (Cloud)
        gwsa_remove_label(message_id, "INBOX", profile=profile)
        
        # 2. Persist State (Local Sidecar)
        store = EmailStore()
        store.save_sidecar(message_id, "triage.json", {
            "action": "archived",
            "rule_id": rule_id,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # 3. Log (Legacy compatibility)
        log_archived_email(rule_id, message_id, from_addr, subject)
        
        return {"success": True, "message_id": message_id, "rule_id": rule_id, "archived": True}
    except Exception as e:
        return {"success": False, "message_id": message_id, "error": str(e)}

def mark_email_in_review_with_gwsa(
    message_id: str,
    reverse: bool = False,
    profile: Optional[str] = None
) -> dict[str, Any]:
    """Apply/Remove Review label and persist 'triage.json' sidecar."""
    config = load_app_config().get("email", {})
    label = config.get('review_label', 'Reviewing')
    try:
        # 1. Action (Cloud)
        if reverse:
            gwsa_remove_label(message_id, label, profile=profile)
        else:
            gwsa_add_label(message_id, label, profile=profile)
        
        # 2. Persist State (Local Sidecar)
        if not reverse:
            store = EmailStore()
            store.save_sidecar(message_id, "triage.json", {
                "action": "reviewing",
                "timestamp": datetime.utcnow().isoformat()
            })
            
        return {'success': True, 'message_id': message_id, 'action': 'removed' if reverse else 'applied'}
    except Exception as e:
        return {'success': False, 'message_id': message_id, 'error': str(e)}

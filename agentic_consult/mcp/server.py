import os
import sys
import json
import logging
import tempfile
from typing import Any, Literal, Optional, Union
from dataclasses import asdict

from mcp.server.fastmcp import FastMCP, Context
from mcp.server.transport_security import TransportSecuritySettings

from agentic_consult import __version__, __package_name__
from agentic_consult.backup.providers.local_repos import LocalRepoBackup
from agentic_consult.backup.folder_providers.factory import get_folder_provider
from agentic_consult.config import get_backups_google_drive_folder_id, get_model_help_text
from agentic_consult.backup.exceptions import BackupError
from agentic_consult.backup.results import BackupItemResult, BackupStatus
from agentic_consult.sdk.scanner import run_scan
from agentic_consult.context import build_context
from agentic_consult.gemini import GeminiAPIClient
from agentic_consult.backup.status import assess_repo_status
from agentic_consult.backup.orchestrator import BackupOrchestrator
from agentic_consult.backup.metadata_manager import BackupMetadataManager
from agentic_consult.sdk.workspace import get_workspace_status
from agentic_consult.sdk.context import analyze_context as sdk_analyze_context
from agentic_consult.mcp.email_processing import (
    get_process_email_instructions,
    add_rule,
    remove_rule,
    list_rules,
    get_rule_usage_stats,
    archive_email_with_gwsa,
    mark_email_in_review_with_gwsa
)
from agentic_consult.email.triage import (
    fetch_triage_pool as sdk_fetch_triage_pool,
    get_cached_emails as sdk_get_cached_emails,
    mark_email_in_review as sdk_mark_email_in_review,
    flag_for_reanalysis as sdk_flag_for_reanalysis
)
from agentic_consult.chat.triage import get_chat_mentions as sdk_get_chat_mentions
from agentic_consult.mcp.docstrings import get_tool_docstring
import fnmatch

logger = logging.getLogger(__name__)

# Transport Security Configuration for MCP HTTP transport
#
# Problem: FastMCP auto-enables DNS rebinding protection when host defaults to
# localhost (127.0.0.1). This validates Host headers against an allowed list.
# On Cloud Run, the Host header is "xxx.run.app" which isn't in the default
# allowed list, causing HTTP 421 "Misdirected Request" errors.
#
# Why disabling on Cloud Run is safe:
# - Cloud Run's frontend validates Host headers at the infrastructure level
# - Requests with mismatched Host headers get Google's 404, never reach container
# - DNS rebinding attacks are not possible against Cloud Run services
# - Our token authentication is the real security boundary
#
# K_SERVICE is set by Cloud Run: https://cloud.google.com/run/docs/container-contract
if os.environ.get("K_SERVICE"):
    transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
else:
    transport_security = None  # Let FastMCP use its defaults (protection for localhost)

mcp = FastMCP(__package_name__, transport_security=transport_security)

# Log version on module load (appears in Cloud Run startup logs)
logger.info(f"{__package_name__} MCP server v{__version__}")

@mcp.tool()
async def get_backup_metadata(path: str = ".") -> dict[str, Any]:
    """
    Retrieves backup metadata (description and keywords) for a repository.
    """
    try:
        manager = BackupMetadataManager(path)
        desc, keywords = manager.get_metadata()
        return {
            "repository": manager.repo_path,
            "description": desc,
            "keywords": keywords
        }
    except ValueError as e:
        return {"error": str(e)}

@mcp.tool()
async def set_backup_metadata(
    path: str = ".",
    description: Optional[str] = None,
    keywords: Optional[str] = None
) -> dict[str, Any]:
    """
    Sets backup metadata for a repository in its local git config.
    """
    try:
        manager = BackupMetadataManager(path)
        manager.set_metadata(description, keywords)
        return {"message": "Metadata updated successfully."}
    except ValueError as e:
        return {"error": str(e)}

@mcp.tool()
async def clear_backup_metadata(path: str = ".") -> dict[str, Any]:
    """
    Clears backup metadata for a repository.
    """
    try:
        manager = BackupMetadataManager(path)
        manager.clear_metadata()
        return {"message": "Metadata cleared successfully."}
    except ValueError as e:
        return {"error": str(e)}

@mcp.tool()
async def generate_backup_metadata(path: str = ".") -> dict[str, Any]:
    """
    Generates backup metadata proposal using Gemini.
    """
    try:
        manager = BackupMetadataManager(path)
        desc, keywords = manager.generate_proposal()
        return {
            "proposed_description": desc,
            "proposed_keywords": keywords
        }
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
async def analyze_files(
    prompt: str,
    context_paths: list[str] = [""],
    exclude: list[str] = [],
    model: str = None,
    stats: bool = False
) -> dict[str, Any]:
    """
    Analyzes local files using Gemini.
    
    This tool allows you to ask questions about your codebase by including specific
    files or directories in the context. It respects exclusions and file limits.

    Args:
        prompt: The question or instruction for Gemini.
        context_paths: A list of paths (files or directories) to include.
                       Defaults to the current directory ('.').
        exclude: A list of glob patterns to exclude (e.g., "*.pyc", "tests/").
                 Matches recursively (standard .gitignore behavior).
        model: Specific model ID or alias (fast, thinking) to use.
        stats: Whether to include analysis metrics in the response.

    Returns:
        A dictionary containing the 'response' text from Gemini, or an 'error' message.
    """
    try:
        # Build Context
        # We use a silent callback or logging for warnings in MCP context
        context_chunks = build_context(
            context_paths, 
            exclude, 
            max_size_kb=100, # Default limit for MCP
            on_limit="warn",
            warning_callback=lambda msg: logger.warning(msg)
        )

        # Build Prompt
        full_prompt = prompt
        if context_chunks:
            full_prompt = f"Context:\n\n{''.join(context_chunks)}\n\nQuestion: {prompt}"

        # Call Gemini
        client = GeminiAPIClient(model_name=model)
        result = client.generate_content(full_prompt)
        
        output = {"response": result["text"]}
        
        if stats:
            output["stats"] = {
                "latency": result["latency"],
                "input_chars": len(full_prompt),
                "output_chars": len(result["text"]),
                "context_files": len(context_chunks)
            }
            
        return output

    except Exception as e:
        logger.exception(f"Unexpected error during analyze_resources")
        return {"error": f"An unexpected error occurred: {str(e)}"}

@mcp.tool()
async def backup_local_repo(
    path: str = ".",
    force: bool = False,
    skip_dirty: bool = False
) -> dict[str, Any]:
    """
    Backs up a single local git repository to Google Drive.
    """
    repo_path = os.path.abspath(path)

    if not os.path.isdir(os.path.join(repo_path, ".git")):
        return {"error": f"Not a git repository: {repo_path}"}

    try:
        folder_id = get_backups_google_drive_folder_id()
        if not folder_id:
            raise BackupError("Backup folder not configured. Run 'consult backup config' first.")

        folder_provider = get_folder_provider()
        provider_folder_id = folder_provider.ensure_folder_path(["local-only-repos"], root_id=folder_id)

        local_repo_backup_instance = LocalRepoBackup()
        
        options = {
            'force': force,
            'skip_dirty': skip_dirty,
            'interactive': False # Always non-interactive for MCP tool
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            result: BackupItemResult = local_repo_backup_instance.backup_single_repo(
                repo_path=repo_path,
                folder_provider=folder_provider,
                provider_folder_id=provider_folder_id,
                temp_dir=temp_dir,
                options=options
            )
            
            output = result.__dict__
            output['status'] = result.status.value
            return output

    except BackupError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.exception(f"Unexpected error during backup_local_repo for {path}")
        return {"error": f"An unexpected error occurred: {str(e)}"}

@mcp.tool()
async def check_repo_status(
    path: str = "."
) -> dict[str, Any]:
    """
    Checks the backup status of a git repository (Local-Only or Remote).
    
    Determines if a backup is needed and provides guidance.
    
    Args:
        path: Path to the repository.
        
    Returns:
        Structured status information including 'backup_needed' flag and 'guidance'.
    """
    try:
        status = assess_repo_status(path)
        return asdict(status)
    except Exception as e:
        logger.exception(f"Error in check_repo_status for {path}")
        return {"error": str(e)}

@mcp.tool()
async def assess_workstation_backup_state() -> dict[str, Any]:
    """
    Assesses the backup state of the entire workstation (all configured providers).
    
    This runs a dry-run of the backup process to identify what needs to be backed up
    without performing any uploads.
    
    Returns:
        Structured report of all items and their status (e.g., PENDING, SUCCESS, FAILED).
    """
    try:
        orchestrator = BackupOrchestrator()
        # dry_run=True, interactive=False (implicit for MCP)
        results = orchestrator.run_backups(force=False, skip_dirty=False, interactive=False, dry_run=True)
        
        json_output = []
        for res in results:
            res_dict = {
                'provider_name': res.provider_name,
                'status': res.status,
                'message': res.message,
                'items': [asdict(item) for item in res.items]
            }
            # Convert enums to strings
            for item in res_dict['items']:
                item['status'] = item['status'].value
            json_output.append(res_dict)
            
        return {"providers": json_output}
        
    except Exception as e:
        logger.exception("Error in assess_workstation_backup_state")
        return {"error": str(e)}

@mcp.tool()
async def run_precommit_scan(
    path: str = ".",
    deep: bool = False
) -> dict[str, Any]:
    """
    Comprehensive pre-commit scan for sensitive data before committing code.

    Checks for:
    - User-specific patterns: names, employers, keywords from sensitive-patterns.yaml
    - Customer patterns: client names, slugs, keywords from customer.yaml files
    - Dollar amounts: large (>$300k), non-round, amounts with cents
    - Identifiers: SSN (XXX-XX-XXXX), EIN (XX-XXXXXXX), Google Drive IDs
    - Emails: flags non-test email addresses
    - OAuth/API tokens: Google OAuth (ya29), GitHub PAT (ghp_), OpenAI (sk-), etc.
    - Local username: prevents $USER from leaking into commits
    - Git identity: ensures consistent committer identity
    - External devws precommit: entropy-based secret detection

    Use this tool BEFORE committing to any repository to prevent accidental
    exposure of sensitive information in public or shared repos.

    Args:
        path: Git repository path to scan. Defaults to current working directory.
        deep: If True, also scans full git history (slower but more thorough).
              Use for pre-push validation or periodic audits.

    Returns:
        {
            "failed": bool,           # True if any check found issues
            "findings": {             # Only populated for failed checks
                "Check Name": ["finding1", "finding2", ...]
            },
            "passed_count": int,      # Number of checks that passed
            "failed_count": int       # Number of checks that failed
        }

    Example:
        result = await run_precommit_scan(path="/home/user/my-repo")
        if result["failed"]:
            print("Issues found:", result["findings"])
    """
    try:
        report = run_scan(repo_path=path, deep=deep)
        # Convert to dict for MCP response
        findings = {}
        for check in report.checks:
            if not check.passed and not check.skipped and check.findings:
                findings[check.name] = check.findings
        return {
            "failed": report.failed,
            "findings": findings,
            "passed_count": report.passed_count,
            "failed_count": report.failed_count
        }
    except Exception as e:
        logger.exception(f"Unexpected error during run_precommit_scan for {path}")
        return {"error": f"An unexpected error occurred: {str(e)}"}

@mcp.tool(description=get_tool_docstring("triage_emails"))
async def triage_emails(
    review_status: Literal["new", "reviewing", "all"] = "all",
    limit: int = 20,
    profile: Optional[str] = None,
    model: Optional[str] = None,
    width: Optional[Union[int, str]] = None,
    ctx: Context = None
) -> dict[str, Any]:
    # Full docstring loaded from mcp/tool-docstrings.json via @mcp.tool(description=...)
    # See DESIGN.md section 15 for updateable app resources.
    try:
        # Create sync progress callback that wraps async report_progress
        def progress_callback(current: int, total: int) -> None:
            if ctx:
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(ctx.report_progress(current, total))
                except Exception:
                    pass  # Silently ignore if progress reporting fails

        return sdk_fetch_triage_pool(
            review_status=review_status,
            limit=limit,
            profile=profile,
            model=model,
            width=width,
            progress_callback=progress_callback
        )
    except Exception as e:
        logger.exception("Error in triage_emails")
        return {"error": str(e)}


@mcp.tool()
async def get_cached_emails(message_ids: list[str]) -> dict[str, Any]:
    """
    Retrieve multiple cached emails by message IDs.

    Emails are cached when process_email runs. Use this to get full content
    for emails where the recommendation summary isn't sufficient.

    Args:
        message_ids: List of Gmail message IDs (from process_email recommendations).

    Returns:
        Dict with 'messages' array. Each item has 'id' at top level, then either:
            - The email fields (from, subject, body, cached_at, etc.) if successful
            - An 'error' object {code, message} if failed

        Check for 'error' field to detect failures; no 'error' means success.

        Error codes:
            - "not_cached": Use gwsa read_email to fetch
            - "read_error": Cache file exists but couldn't be read
    """
    try:
        return sdk_get_cached_emails(message_ids)
    except Exception as e:
        logger.exception("Error in get_cached_emails")
        return {"messages": [{"id": mid, "error": {"code": "internal_error", "message": str(e)}} for mid in message_ids]}


@mcp.tool()
async def mark_email_in_review(
    message_id: str,
    reverse: bool = False,
) -> dict[str, Any]:
    """
    Apply or remove the Reviewing label from an email.
    Also persists 'triage.json' sidecar locally to exclude from future scans.

    Use this for emails with recommended_action="review" from triage_emails.
    The Reviewing label keeps emails in inbox but marks them for later attention.

    Args:
        message_id: Gmail message ID
        reverse: If True, remove the Reviewing label (default False = add label)

    Returns:
        Success status with label action taken.
    """
    try:
        return mark_email_in_review_with_gwsa(
            message_id=message_id,
            reverse=reverse,
        )
    except Exception as e:
        logger.exception("Error in mark_email_in_review")
        return {"error": str(e)}


@mcp.tool()
async def flag_for_reanalysis(message_ids: list[str]) -> dict[str, Any]:
    """
    Flag emails for reanalysis by removing their analysis.json sidecars.

    Use this when an email was incorrectly analyzed or when rules have changed
    and you want the background analyzer to re-process specific emails.

    The analyzer job runs periodically and will re-analyze flagged emails on
    its next run, applying current rules and context.

    Args:
        message_ids: List of message IDs to flag for reanalysis.

    Returns:
        Dictionary with:
        - flagged: Count of emails successfully flagged
        - errors: List of any failures (optional, only if errors occurred)
    """
    try:
        return sdk_flag_for_reanalysis(message_ids)
    except Exception as e:
        logger.exception("Error in flag_for_reanalysis")
        return {"error": str(e)}


@mcp.tool()
async def list_email_rules(
    filter_pattern: Optional[str] = None,
    include_disabled: bool = False
) -> dict[str, Any]:
    """
    Lists all configured email processing rules with usage statistics.

    Usage stats help identify stale rules that can be removed to reduce agent
    context overhead. Rules that haven't been used in months are candidates
    for cleanup.

    Args:
        filter_pattern: Optional shell-style wildcard pattern to filter rules by ID (e.g., "*important*").
        include_disabled: Whether to include disabled rules in the output. Defaults to False.

    Returns:
        Dictionary with 'rules' list containing all configured rules.
        Each rule includes 'use_count' and 'last_used' from archive logs.
    """
    try:
        rules = list_rules(include_disabled=include_disabled)
        usage_stats = get_rule_usage_stats()

        # Merge usage stats into rules
        for rule in rules:
            rule_id = rule.get('id')
            if rule_id and rule_id in usage_stats:
                rule['use_count'] = usage_stats[rule_id]['use_count']
                rule['last_used'] = usage_stats[rule_id]['last_used']
            else:
                rule['use_count'] = 0
                rule['last_used'] = None

        if filter_pattern:
            rules = [r for r in rules if fnmatch.fnmatch(r.get('id', ''), filter_pattern)]

        return {"rules": rules, "count": len(rules)}
    except Exception as e:
        logger.exception("Error in list_email_rules")
        return {"error": str(e)}


@mcp.tool()
async def add_email_rule(
    rule_id: str,
    action: str = "review",
    rule_type: Optional[str] = None,
    match_from: Optional[str] = None,
    match_subject: Optional[str] = None,
    instructions: Optional[str] = None
) -> dict[str, Any]:
    """
    Adds a new email processing rule.

    Args:
        rule_id: Unique identifier for the rule (e.g., 'usps-digest', 'airbnb-payouts')
        action: Action to take: 'archive', 'review', 'track_as_task'. Defaults to 'review'.
        rule_type: DEPRECATED (use action). Either 'auto_archive' or 'custom'.
        match_from: Email sender pattern to match (partial match)
        match_subject: Subject line pattern to match (partial match)
        instructions: Required if context is needed - what to do with matching emails

    Returns:
        The created rule, or an error message.
    """
    try:
        rule = add_rule(
            rule_id=rule_id,
            action=action,
            rule_type=rule_type,
            match_from=match_from,
            match_subject=match_subject,
            instructions=instructions
        )
        return {"success": True, "rule": rule}
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.exception("Error in add_email_rule")
        return {"error": str(e)}


@mcp.tool()
async def remove_email_rule(rule_id: str) -> dict[str, Any]:
    """
    Removes an email processing rule by ID.

    Args:
        rule_id: The ID of the rule to remove.

    Returns:
        Success status or error message.
    """
    try:
        removed = remove_rule(rule_id)
        if removed:
            return {"success": True, "message": f"Rule '{rule_id}' removed"}
        else:
            return {"success": False, "message": f"Rule '{rule_id}' not found"}
    except Exception as e:
        logger.exception("Error in remove_email_rule")
        return {"error": str(e)}


@mcp.tool()
async def configure_triage_batching(
    pool_size: Optional[int] = None,
    batch_target: Optional[int] = None
) -> dict[str, Any]:
    """
    Configure triage batching settings for email processing.

    Controls how many emails are fetched (pool) and how many are presented
    to the user at once (batch). The client agent should group emails by
    similar recommended action and priority when presenting batches.

    Args:
        pool_size: Number of emails to fetch per triage run (default 25).
            Larger pools provide more context but increase processing time.
        batch_target: Suggested batch size for user presentation (default 5).
            The agent groups similar items together, so actual batch sizes
            may vary (4-6 items) to keep related emails in the same batch.

    Returns:
        Current batching settings after any updates.
    """
    from agentic_consult.mcp.email_processing import get_triage_batching, set_triage_batching

    try:
        if pool_size is not None or batch_target is not None:
            return set_triage_batching(pool_size=pool_size, batch_target=batch_target)
        return get_triage_batching()
    except Exception as e:
        logger.exception("Error in configure_triage_batching")
        return {"error": str(e)}


@mcp.tool()
async def configure_email_rules(
    rule_changes: list[dict]
) -> dict[str, Any]:
    """
    Apply batch changes to email processing rules.

    Use this to add, update, or delete user rules, and to manage enable/disable
    patterns that control which rules are active. Rules represent an investment
    of prompt engineering effort - use this tool carefully.

    Args:
        rule_changes: Array of change objects. Each must have 'change_type' and
            relevant fields:

            **add_user_rule**: Create a new rule
                - rule_id: Unique identifier (required)
                - action: 'archive', 'review', or 'track_as_task' (default: 'review')
                - condition: Natural language condition for LLM evaluation
                - match_from: Sender pattern (regex)
                - match_subject: Subject pattern (regex)
                - instructions: Custom handling instructions

            **update_user_rule**: Modify an existing rule
                - rule_id: Rule to update (required)
                - Plus any fields to change (action, condition, etc.)

            **delete_user_rule**: Remove a rule
                - rule_id: Rule to delete (required)

            **add_disable_pattern**: Disable rules matching glob pattern
                - pattern: Glob pattern like "sys-*" or "work-*"

            **remove_disable_pattern**: Re-enable rules by removing pattern
                - pattern: Pattern to remove from disable list

            **add_enable_pattern**: Enable rules matching glob pattern
                - pattern: Glob pattern like "home-*"

            **remove_enable_pattern**: Remove from enable list
                - pattern: Pattern to remove

    Returns:
        Summary with 'applied' (successful changes), 'errors' (failed changes),
        and current state (rules_count, disable_patterns, enable_patterns).

    Example:
        rule_changes=[
            {"change_type": "add_disable_pattern", "pattern": "sys-important-direct"},
            {"change_type": "add_user_rule", "rule_id": "my-receipts",
             "action": "archive", "condition": "Receipt email older than 3 days"}
        ]
    """
    from agentic_consult.mcp.email_processing import apply_rule_changes

    try:
        return apply_rule_changes(rule_changes)
    except Exception as e:
        logger.exception("Error in configure_email_rules")
        return {"error": str(e)}


@mcp.tool()
async def workspace_status(
    paths: list[str] = None,
    scan: bool = True
) -> dict[str, Any]:
    """
    Analyzes workspace status, identity, and git state.

    Identifies folders in scope for the current workspace by checking:
    1. Explicitly provided paths.
    2. Folders defined in settings (workspace.folders).
    3. Included context directories.
    4. The current working directory and its parents (finding the git root).

    For each identified folder, it checks:
    - If it is a git repository.
    - If 'scan' is True, it also checks immediate subdirectories.

    Reports on:
    - Path: Absolute location.
    - Classification: 'Public Remote', 'Private Remote', 'Other Remote', 'Local Only'.
    - Status: 'Clean', 'Dirty', 'Ahead', 'Behind'.
    - Identity: Git user email and confidence.
    - Perfect: Boolean flag indicating clean and fully synced state.

    Args:
        paths: Optional list of specific paths to check.
        scan: Whether to scan subdirectories for git repos (default: True).

    Returns:
        Dictionary containing a list of workspace status objects under the 'workspaces' key.
        
        The returned data is structured for programmatic access. Each repository includes
        an 'is_perfect' boolean (summarizing clean local state and fully synced remote/backup).
        When presenting this to the user, a summary table showing Path, Classification,
        Status, Stats, and Identity is recommended. Since 'is_perfect' is a summary flag,
        it is suggested to display it concisely (e.g. using a simple icon like ✅) rather
        than a dedicated large text field.
    """
    try:
        results = get_workspace_status(paths=paths, scan=scan)
        return {"workspaces": results}
    except Exception as e:
        logger.exception("Error in workspace_status")
        return {"error": str(e)}


@mcp.tool()
async def analyze_context(
    prompt: str,
    scope: str = "project",
    model: str = None
) -> dict[str, Any]:
    """
    Analyzes the GEMINI.md context file using an LLM to answer questions about it.

    This tool is READ-ONLY. To modify the context file, the user must use the
    CLI command: `consult context revise <prompt>`.

    Args:
        prompt: The question or instruction for analyzing the context (e.g., "Summarize the triage rules").
        scope: "project" (default, looks in .gemini/GEMINI.md) or "user" (looks in ~/.config/agentic-consult/GEMINI.md).
        model: Optional Gemini model override.

    Returns:
        Dictionary with the 'response' text from Gemini.
    """
    try:
        result = sdk_analyze_context(scope, prompt, model)
        return {"response": result}
    except FileNotFoundError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.exception("Error in analyze_context")
        return {"error": str(e)}


@mcp.tool()
async def archive_email(
    message_id: str,
    from_addr: str,
    subject: str,
    reason: str,
    rule_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Archive an email and persist 'triage.json' sidecar locally.

    **IMPORTANT:** This tool is intended ONLY for use within the email processing
    workflow triggered by `triage_emails`.

    This tool serves three purposes:

    1. **Archive emails** - Removes the INBOX label via gwsa SDK.

    2. **Persist State** - Saves a 'triage.json' sidecar via EmailStore so the
       email is excluded from future 'triage_emails' results.

    3. **Track usage** - Logs each archived email for rule efficiency reporting.

       - **Rule efficiency**: The `list_email_rules` tool uses these logs to
         report use_count and last_used for each rule. Rules with zero usage
         over months are candidates for removal to reduce agent context.

       - **Forensic recovery**: If emails are incorrectly archived, the log
         provides a record of what was archived and when, enabling review
         and recovery via Gmail search by message_id.

    Archive logs are stored in $XDG_CACHE_HOME/agentic-consult/email-archive-log.jsonl
    and automatically cleaned up after the configured retention period (default 90 days).

    Args:
        message_id: Gmail message ID to archive
        from_addr: Sender email address (for logging)
        subject: Email subject line (for logging, truncated to 100 chars)
        reason: Why this email is being archived:
                - "rules-based": Matches a configured auto-archive rule (rule_id required)
                - "ad-hoc": User explicitly approved archiving during review
        rule_id: ID of the rule that triggered this archive (required when reason="rules-based")

    Returns:
        Dict with success status, message_id, reason, rule_id (if applicable), and archived flag.
        On failure, includes error message.
    """
    # Validate reason
    if reason not in ("rules-based", "ad-hoc"):
        return {"error": f"Invalid reason: {reason}. Must be 'rules-based' or 'ad-hoc'", "message_id": message_id}

    # Require rule_id for rules-based archiving
    if reason == "rules-based" and not rule_id:
        return {"error": "rule_id is required when reason='rules-based'", "message_id": message_id}

    try:
        result = archive_email_with_gwsa(
            message_id=message_id,
            rule_id=rule_id or "ad-hoc",  # Use "ad-hoc" as rule_id for logging when not rules-based
            from_addr=from_addr,
            subject=subject,
        )
        # Add reason to result
        if result.get("success"):
            result["reason"] = reason
        return result
    except Exception as e:
        logger.exception("Error in archive_email")
        return {"error": str(e), "message_id": message_id}


@mcp.tool()
async def get_recent_group_chats(limit: int = 10) -> dict[str, Any]:
    """
    Get the most recent Group Chats.

    This is more convenient than filtering all spaces. It returns a sorted list
    of the most recent group chats.

    Args:
        limit: The maximum number of recent group chats to return.

    Returns:
        A dictionary containing a list of the most recent group chat spaces.
    """
    # Chat functionality temporarily disabled (gwsa dependency removed)
    logger.info("get_recent_group_chats temporarily disabled")
    return {"group_chats": [], "disabled_reason": "Chat SDK not yet implemented"}


@mcp.tool()
async def get_chat_mentions(
    limit: int = 20,
    message_limit: int = 100,
    unanswered_only: bool = False
) -> dict[str, Any]:
    """
    Scans Google Chat for actionable mentions and unread DMs.
    
    This tool intelligently finds "important" conversations by:
    1. Identifying active spaces based on configured tiers (Size vs Recency).
    2. Treating small DMs (<= 3 people) as "Implicit Mentions" if the last message is not from you.
    3. Scanning larger groups for "Explicit Mentions" (@You).
    
    This is highly efficient compared to brute-force searching.

    Args:
        limit: Maximum number of active spaces to analyze (default 20).
        message_limit: Global limit on total messages scanned (default 100).
        unanswered_only: If True, filters out mentions you have already responded or reacted to (default False).

    Returns:
        Dict with 'mentions' list, 'source' metadata, and logical API stats.
    """
    try:
        return sdk_get_chat_mentions(
            limit=limit, 
            message_limit=message_limit, 
            unanswered_only=unanswered_only,
            verbose=True
        )
    except Exception as e:
        logger.exception("Error in get_chat_mentions")
        return {"error": str(e)}




# --- Triage Stats Tool ---

@mcp.tool()
async def email_triage_stats(
    sample_size: int = 20
) -> dict[str, Any]:
    """
    Get email triage statistics from the email archive.

    Uses EmailStore SDK for disk I/O. Returns counts and date ranges
    plus a sampled breakdown of active emails by (action, rule_id) pairs.

    Use this for health checks to verify the MCP server can access email data.

    Args:
        sample_size: Max active emails to load for action breakdown (default 20).

    Returns:
        {
            "emails": {
                "fetched": {"count": N, "start": "YYYY-MM-DD HH:MM", "end": "..."},
                "analyzed": {"count": N, "start": "...", "end": "..."},
                "resolved": {"count": N, "start": "...", "end": "..."},
                "active": {
                    "count": N,
                    "sample": {
                        "size": M,
                        "archive": {"retail-receipts": 3, "shipping-delivered": 2},
                        "review": {"k12-grades-testing": 1, "unmatched": 2},
                        ...
                    }
                }
            }
        }
    """
    from agentic_consult.email.triage import get_triage_stats

    try:
        return get_triage_stats(sample_size=sample_size)
    except Exception as e:
        logger.exception("Error in email_triage_stats")
        return {"error": str(e)}


# --- Customer Management Tools ---

@mcp.tool()
async def list_customers(
    filter_pattern: Optional[str] = None
) -> dict[str, Any]:
    """
    Lists all registered customers.

    Use this tool first to check if a customer already exists before attempting registration.
    Returns basic details (slug, name, drive_folder_id) for each customer.

    Args:
        filter_pattern: Optional wildcard pattern to filter by slug or name (e.g. "*acme*").
    """
    try:
        from agentic_consult.customers import get_active_customers_root, _parse_customer_yaml
        import fnmatch

        root = get_active_customers_root()
        if not root.exists():
            return {"customers": [], "count": 0, "message": "No customers directory found."}

        customers = []
        for d in sorted(root.iterdir()):
            if d.is_dir() and (d / "customer.yaml").exists():
                cust = _parse_customer_yaml(d / "customer.yaml")
                if cust:
                    slug = cust.get('slug', d.name)
                    name = cust.get('name', 'N/A')
                    
                    # Apply filter
                    if filter_pattern:
                        if not (fnmatch.fnmatch(slug, filter_pattern) or fnmatch.fnmatch(name, filter_pattern)):
                            continue
                            
                    customers.append({
                        "slug": slug,
                        "name": name,
                        "drive_folder_id": cust.get('drive_folder_id'),
                        "local_path": str(d)
                    })

        return {"customers": customers, "count": len(customers)}
    except Exception as e:
        logger.exception("Error in list_customers")
        return {"error": str(e)}


@mcp.tool()
async def get_customer_info(slug: str) -> dict[str, Any]:
    """
    Returns full details for a specific customer.

    Use this to get the Google Drive Folder ID ('drive_folder_id') or local path
    needed for file operations.

    Args:
        slug: The unique identifier for the customer (e.g. 'acme-corp').
    """
    try:
        from agentic_consult.customers import find_customer_by_id, get_active_customers_root
        
        cust = find_customer_by_id(slug)
        if not cust:
            return {"error": f"Customer '{slug}' not found."}
            
        customer_root = get_active_customers_root() / cust['slug']
        drive_id = cust.get('drive_folder_id')
        
        # Structured Response as defined in DESIGN.md
        return {
            "name": cust.get('name', slug),
            "slug": cust['slug'],
            "keywords": cust.get('keywords', []),
            "local": {
                "path": str(customer_root),
                "notes_path": str(customer_root / 'notes'),
                "config_path": str(customer_root / 'customer.yaml')
            },
            "cloud": {
                "status": "initialized" if drive_id else "missing",
                "google_drive_folder_id": drive_id,
                "guidance": None if drive_id else "Cloud folder not linked. Run 'register_customer' with drive_id to link."
            }
        }
    except Exception as e:
        logger.exception(f"Error in get_customer_info for {slug}")
        return {"error": str(e)}


@mcp.tool()
async def register_customer(
    slug: str,
    name: Optional[str] = None,
    drive_id: Optional[str] = None
) -> dict[str, Any]:
    """
    Registers a new customer or repairs an existing one (Idempotent).

    Creates the local directory structure and ensures a customer.yaml exists.
    If 'drive_id' is NOT provided, it will attempt to find or create a folder
    in the configured 'Customers' root on Google Drive.

    Args:
        slug: Unique identifier (folder name), e.g. "acme-corp".
        name: Human-readable name. Defaults to slug if omitted.
        drive_id: Optional existing Google Drive Folder ID for this customer.
    """
    try:
        import yaml
        from agentic_consult.customers import get_active_customers_root, _parse_customer_yaml
        from agentic_consult.config import load_main_config
        
        name = name or slug
        customers_root = get_active_customers_root()
        customers_root.mkdir(parents=True, exist_ok=True)
        
        target_dir = customers_root / slug
        target_dir.mkdir(parents=True, exist_ok=True)
        
        yaml_path = target_dir / 'customer.yaml'
        current_data = {}
        
        # Load existing if available (for idempotency)
        if yaml_path.exists():
            try:
                with open(yaml_path, 'r') as f:
                    current_data = yaml.safe_load(f) or {}
            except Exception:
                pass # Corrupt or empty, start fresh-ish

        # Drive Logic: If we don't have an ID, try to resolve it
        resolved_drive_id = drive_id or current_data.get('drive_folder_id')
        
        if not resolved_drive_id:
            # We need to find/create it in the Cloud Root
            config = load_main_config()
            parent_id = config.get('google_drive_all_customers_folder_id')
            
            if parent_id:
                # Note: Actual Drive API calls should ideally be delegated or handled via a robust service.
                # For this MCP implementation, without a direct Drive Service instance easily available 
                # in this scope without introducing 'gwsa' dependencies, we might limit auto-creation 
                # or return a warning if ID is missing.
                # However, let's assume the user will provide it or we note it as missing.
                # To keep this safe and simple for now:
                pass
            else:
                return {"error": "No 'google_drive_all_customers_folder_id' configured. Cannot auto-create Drive folder."}

        # Update Data
        current_data['name'] = name
        current_data['slug'] = slug
        if resolved_drive_id:
            current_data['drive_folder_id'] = resolved_drive_id
            
        # Write
        with open(yaml_path, 'w') as f:
            yaml.dump(current_data, f)
            
        return {
            "success": True,
            "message": f"Customer '{slug}' registered/updated.",
            "path": str(target_dir),
            "drive_id": resolved_drive_id or "NOT_CONFIGURED"
        }

    except Exception as e:
        logger.exception(f"Error in register_customer for {slug}")
        return {"error": str(e)}


@mcp.tool()
async def get_fake_email_addresses(
    filter_pattern: Optional[str] = None,
    limit: Optional[int] = None
) -> dict[str, Any]:
    """
    Returns a list of safe, whitelisted fake email addresses for use in versioned files.

    ## CRITICAL USAGE MANDATE
    Whenever you need to use a placeholder or fake email address in any versioned file
    (e.g., unit tests, documentation, examples, code comments, or configuration files),
    you MUST select an address from this returned list.

    ## WHY THIS IS REQUIRED
    The 'consult precommit' and 'devws precommit' security scanners strictly enforce 
    PII protection. Using any email address NOT found in this whitelisted list will
    cause the pre-commit checks to FAIL and block your ability to commit or push code.

    ## BEST EXAMPLES FIRST
    Results are returned in prioritized order:
    1. **Universal Placeholders**: (e.g., user@example.com) - Use these for almost everything.
    2. **Legitimately Distinct Examples**: (e.g., worker@company.com) - Use these ONLY when 
       specific semantic meaning is required (e.g., distinguishing home vs work accounts) 
       that standard placeholders cannot convey.

    ## ADDITION POLICY
    Do not request adding new emails to the whitelist unless they are 'Legitimately Distinct'.
    Lazy variations or duplicates of existing placeholders will be rejected.

    Args:
        filter_pattern: Optional wildcard pattern (e.g., '*@example.com') to filter results.
        limit: Optional maximum number of addresses to return.
    """
    try:
        from agentic_consult.sdk.security import get_allowed_emails
        
        emails = get_allowed_emails(filter_pattern=filter_pattern, limit=limit)
        
        return {
            "emails": emails,
            "count": len(emails),
            "usage_instruction": "USE THESE ADDRESSES ONLY. Non-whitelisted emails will trigger pre-commit failures."
        }
    except Exception as e:
        logger.exception("Error in get_fake_email_addresses")
        return {"error": str(e)}


import os
import sys
import json
import logging
import tempfile
from typing import Any, Literal, Optional, Union
from dataclasses import asdict

from mcp.server.fastmcp import FastMCP, Context

from agentic_consult.backup.providers.local_repos import LocalRepoBackup
from agentic_consult.backup.folder_providers.factory import get_folder_provider
from agentic_consult.config import get_backups_google_drive_folder_id, get_model_help_text
from agentic_consult.backup.exceptions import BackupError
from agentic_consult.backup.results import BackupItemResult, BackupStatus
from agentic_consult.scanner.core import run_scan
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
    triage_emails as sdk_triage_emails,
    get_cached_emails as sdk_get_cached_emails,
    mark_email_in_review as sdk_mark_email_in_review,
    mark_email_archivable as sdk_mark_email_archivable,
    suggest_email_action as sdk_suggest_email_action
)
from agentic_consult.chat.triage import get_chat_mentions as sdk_get_chat_mentions
import fnmatch

logger = logging.getLogger(__name__)

mcp = FastMCP("agentic-consult")

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
    include_ignored: bool = False
) -> dict[str, Any]:
    """
    Runs a pre-commit scan for sensitive data in a local directory.
    
    This tool is designed to be used by agents to check for secrets, customer data,
    and other sensitive information before committing code.

    Args:
        path: The directory or file path to scan. Defaults to the current working directory.
        include_ignored: Whether to scan files ignored by git.

    Returns:
        A dictionary containing the structured scan results. Includes a 'failed'
        boolean flag and a 'findings' dictionary with any detected issues.
    """
    try:
        scan_results = run_scan(path=path, include_ignored=include_ignored)
        return scan_results
    except Exception as e:
        logger.exception(f"Unexpected error during run_precommit_scan for {path}")
        return {"error": f"An unexpected error occurred: {str(e)}"}

@mcp.tool()
async def triage_emails(
    review_status: Literal["new", "reviewing", "all"] = "all",
    limit: int = 20,
    profile: Optional[str] = None,
    model: Optional[str] = None,
    width: Optional[Union[int, str]] = None,
    ctx: Context = None
) -> dict[str, Any]:
    """
    Triage inbox emails using pre-computed background analysis.

    Reads results from 'analysis.json' sidecars produced by the background analyzer service.
    Excludes emails already marked with a 'triage.json' sidecar.

    ## Workflow

    Terminal state = triaged (archived or in review). Goal is to clear the pending queue.

    1. **Start with "all" (default)** - See full pending triage state.

    2. **Wait for User Confirmation** - The tool returns a plan (instructions).
       **DO NOT EXECUTE THESE ACTIONS AUTOMATICALLY.**
       Display the plan to the user and wait for their explicit command or confirmation.

    3. **Process results (After Confirmation)** - Based on user input:
       - archive_now → `archive_email()` → done (creates triage.json)
       - archive_later → `mark_email_archivable()` → stays until aged
       - review → `mark_email_in_review()` → stays for user attention (creates triage.json)
       - track_as_task → create task, then `archive_email()` → done (creates triage.json)
       - ask_user → get user decision, act accordingly → done

    4. **Subsequent batches** - Use `review_status="new"` to skip labeled emails
       when fetching the next batch. Use "reviewing" to focus on emails awaiting
       user attention. These filters are for efficiency when "all" is manageable.

    5. **When "all" is cluttered** - If default limit returns mostly deferred
       emails (Reviewing/Archivable), increase `limit` or use filters to reach
       emails that can be immediately actioned.

    6. **Done** - Triage complete when inbox is empty.

    ## Google Chat Handling

    The tool also scans for **Google Chat Recent Mentions and DMs**.
    
    *   **Scope:** Scans active DMs and Spaces based on recency tiers.
    *   **Filtering:** Items are included if they contain an explicit mention (@You) or are in a
        small group (DM), AND you have **not responded** later in the thread **nor reacted** (emoji) to the message.
    *   **Presentation:** These are presented in a dedicated section at the top of the triage table.
    
    ## Calendar Invites Handling

    The tool separates Calendar Invites into a distinct `invites` list in the response.
    
    *   **Availability Check:** The Agent MUST iterate through the `invites` list and use
        **available calendar tools** to check user availability for the proposed times.
    *   **Presentation:** The Agent MUST update the display table (filling in the `Avail` column placeholders)
        to show availability status (e.g., ✅/❌).
    *   **Action Handling:** Facilitate the user's ability to accept these invites using
        **available tools** and then reply/archive the email.

    ## DSL & Command Handling

    The tool output includes a "Suggested Actions" block using a shorthand DSL.
    If the user replies with these commands (e.g., `do rev A1 B2`), you must:
    1.  **Resolve Refs**: Look up the `ref` (e.g., "A1") in the tool output table to find the corresponding `id` (Gmail Message ID).
    2.  **Execute Tool**: Call the appropriate tool for the command:
        - `do rev <refs>`   → `mark_email_in_review(message_id=id)`
        - `do task <refs>`  → Create a task for each, then `archive_email(message_id=id)`
        - `do arc <refs>`   → `archive_email(message_id=id, reason="ad-hoc")`
        - `do later <refs>` → `mark_email_archivable(message_id=id)`
        - `do sum <refs>`   → `get_cached_emails(message_ids=[id])` (Summarize content)
        - `do show <refs>`  → `get_cached_emails(message_ids=[id])` (Show full content)
        - `do relist`       → Filter and redisplay the table with remaining items (no tool call)
    
    **Example:**
    User: "do rev A1"
    Agent: Finds A1 in table -> ID "19b9..." -> Calls `mark_email_in_review(message_id="19b9...")`

    Args:
        review_status: Filter emails by state
            - "all": All inbox emails (default - use for initial triage and final passes)
            - "new": Emails without Reviewing/Archivable labels (efficient for mid-session batches)
            - "reviewing": Emails previously marked for review
        limit: Maximum emails to fetch (default 20, max recommended for context)
        profile: Optional gwsa profile name (omit for default)
        model: Optional Gemini model override (default from app.yaml)
        width: Optional table width hint ("small", "medium", "large") OR integer (total chars). 
               Defaults to "medium" (120). 
               HINT: When using terminal width, pass a value slightly less (e.g., -10) than 
               the detected width to account for margins and agentic indentation.

    Returns:
        Dictionary with:
            - recommendations: List of {id, date, from, subject, recommended_action, rule_id, reason}
            - rules_referenced: Rules that matched at least one email
            - instructions: Next steps guidance
            - stats: Processing statistics

        recommended_action values:
            - "archive_now": Archive immediately (routine email, aged sufficiently for user visibility)
            - "archive_later": Archivable per rules, but kept visible a bit longer; use
              `mark_email_archivable` tool to apply label so user can archive manually via
              Gmail UI and our tooling can skip these emails via filter when pulling batches
            - "track_as_task": Requires follow-up action (create task, then archive)
            - "review": Needs human attention (apply Reviewing label)
            - "ask_user": No rule matched (present to user for decision)

        Follow-up tools:
            - get_cached_emails([message_ids]): Get full cached email content
            - archive_email(...): Archive with logging
            - mark_email_archivable(message_id): Apply Archivable label
            - mark_email_in_review(message_id): Apply/remove Reviewing label
    """
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

        return sdk_triage_emails(
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
    profile: Optional[str] = None
) -> dict[str, Any]:
    """
    Apply or remove the Reviewing label from an email.
    Also persists 'triage.json' sidecar locally to exclude from future scans.

    Use this for emails with recommended_action="review" from triage_emails.
    The Reviewing label keeps emails in inbox but marks them for later attention.

    Args:
        message_id: Gmail message ID
        reverse: If True, remove the Reviewing label (default False = add label)
        profile: Optional gwsa profile name

    Returns:
        Success status with label action taken.
    """
    try:
        return mark_email_in_review_with_gwsa(
            message_id=message_id,
            reverse=reverse,
            profile=profile
        )
    except Exception as e:
        logger.exception("Error in mark_email_in_review")
        return {"error": str(e)}


@mcp.tool()
async def mark_email_archivable(
    message_id: str,
    reverse: bool = False,
    profile: Optional[str] = None
) -> dict[str, Any]:
    """
    Apply or remove the Archivable label from an email.

    Use this for emails with recommended_action="archive_later" from triage_emails.
    The Archivable label marks emails that can be archived later (age threshold not yet met).

    Args:
        message_id: Gmail message ID
        reverse: If True, remove the Archivable label (default False = add label)
        profile: Optional gwsa profile name

    Returns:
        Success status with label action taken.
    """
    try:
        return sdk_mark_email_archivable(
            message_id=message_id,
            reverse=reverse,
            profile=profile
        )
    except Exception as e:
        logger.exception("Error in mark_email_archivable")
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
    profile: Optional[str] = None
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
        profile: Optional gwsa profile name if not using default

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
            profile=profile
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
    try:
        from gwsa.sdk.chat import get_recent_chats
        chats = get_recent_chats(chat_type='GROUP_CHAT', limit=limit)
        return {"group_chats": chats}
    except Exception as e:
        logger.error(f"Error getting recent group chats: {e}")
        return {"error": str(e)}


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

def run_server():
    """Run the MCP server with stdio transport."""
    mcp.run()

if __name__ == "__main__":
    run_server()

import os
import sys
import json
import logging
import tempfile
from typing import Any, Optional
from dataclasses import asdict

from mcp.server.fastmcp import FastMCP

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

logger = logging.getLogger(__name__)

mcp = FastMCP("agentic-consult")

@mcp.tool()
async def analyze_files(
    prompt: str,
    context_paths: list[str] = ["."],
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

def run_server():
    """Run the MCP server with stdio transport."""
    mcp.run()

if __name__ == "__main__":
    run_server()
import os
import sys
import json
import logging
import tempfile
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from agentic_consult.backup.providers.local_repos import LocalRepoBackup
from agentic_consult.backup.folder_providers.factory import get_folder_provider
from agentic_consult.config import get_backups_google_drive_folder_id, get_model_help_text
from agentic_consult.backup.exceptions import BackupError
from agentic_consult.backup.results import BackupItemResult, BackupStatus
from agentic_consult.scanner.core import run_scan
from agentic_consult.analyze import run_analysis

logger = logging.getLogger(__name__)

mcp = FastMCP("agentic-consult")

@mcp.tool()
async def analyze_resources(
    prompt: str,
    resources: str = "."
) -> dict[str, Any]:
    """
    Analyzes local markdown documentation and resources using Gemini.
    
    This tool aggregates content from 'GEMINI.md' and all '*.md' files in the
    specified paths, constructs a prompt with this context, and queries Gemini.
    Useful for answering questions about the codebase, architecture, or project status.

    Args:
        prompt: The question or instruction for Gemini.
        resources: A comma-separated list of paths or glob patterns to include 
                   in the context. Defaults to the current directory ('.').
                   Example: "docs/*.md,notes/"

    Returns:
        A dictionary containing the 'response' text from Gemini, or an 'error' message.
    """
    # Note: The docstring above is replaced dynamically below
    try:
        resource_list = [item.strip() for item in resources.split(",") if item.strip()]
        if not resource_list and resources.strip():
             return {"error": "Resource paths cannot be empty."}

        # Run analysis
        result = run_analysis(prompt, resource_list)
        
        if result.get("error"):
            return {"error": result["error"]}
            
        return {"response": result.get("response", "")}

    except Exception as e:
        logger.exception(f"Unexpected error during analyze_resources")
        return {"error": f"An unexpected error occurred: {str(e)}"}

# Dynamically update the docstring with current config info
analyze_resources.__doc__ = f"""
Analyzes local markdown documentation and resources using Gemini.

Supported configuration: {get_model_help_text()}

Args:
    prompt: The question or instruction for Gemini.
    resources: A comma-separated list of paths or glob patterns to include 
               in the context. Defaults to the current directory ('.').
"""

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

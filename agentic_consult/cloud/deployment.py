"""Shared deployment logic and configuration parsing."""
import configparser
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, Optional

def get_repo_root() -> Path:
    """Resolve repo root from this file's location."""
    # agentic_consult/cloud/deployment.py -> agentic_consult/cloud -> agentic_consult -> root
    return Path(__file__).parent.parent.parent

def run_git_cmd(cmd: list, cwd: Optional[Path] = None, check: bool = True) -> str:
    """Run a git command and return output."""
    if cwd is None:
        cwd = get_repo_root()
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check)
    return result.stdout.strip()

def get_head_sha() -> str:
    """Get current HEAD SHA."""
    return run_git_cmd(["git", "rev-parse", "HEAD"])

def get_git_repo_slug() -> str:
    """Get 'user/repo' from git remote origin."""
    try:
        url = run_git_cmd(["git", "config", "--get", "remote.origin.url"])
        if url.endswith(".git"):
            url = url[:-4]
        
        # Handle SSH: git@github.com:user/repo
        if "@" in url and ":" in url:
            return url.split(":")[-1]
            
        # Handle HTTPS: https://github.com/user/repo
        parts = url.split("/")
        if len(parts) >= 2:
            return f"{parts[-2]}/{parts[-1]}"
            
        return "unknown/unknown"
    except subprocess.CalledProcessError:
        return "unknown/unknown"

def load_components_config(repo_root: Path, ref: Optional[str] = None) -> Dict[str, Dict[str, str]]:
    """Load component definitions from deploy/components.ini, optionally at specific ref."""
    components_ini = repo_root / "deploy" / "components.ini"
    
    parser = configparser.ConfigParser()
    
    if ref is None:
        # Read from working directory
        parser.read(components_ini)
    else:
        # Read from git at specific ref
        content = run_git_cmd(["git", "show", f"{ref}:deploy/components.ini"], cwd=repo_root)
        parser.read_string(content)

    images = {}
    for section in parser.sections():
        images[section] = dict(parser[section])
    return images

def resolve_image_name(name: str, config: dict, git_slug: str) -> str:
    """Resolve 'auto' image names using git slug."""
    image_name = config.get("image", "")
    if image_name == "auto":
        if name == "mcp":
            return f"{git_slug}-mcp"
        return f"{git_slug}-{name}"
    return image_name

def get_image_url(project_id: str, image_name: str, tag: str, registry: Optional[str] = None) -> str:
    """Construct full image URL.
    
    If registry is provided, use it.
    If image_name looks like a full URL (has domain), use it.
    Otherwise default to gcr.io/project_id/image_name.
    """
    if "/" in image_name and "." in image_name.split("/")[0]:
        # Fully qualified (e.g. ghcr.io/user/repo)
        return f"{image_name}:{tag}"
    
    base = registry or f"gcr.io/{project_id}"
    return f"{base}/{image_name}:{tag}"

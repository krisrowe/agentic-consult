"""SDK for managing customer issues."""

import os
import logging
from pathlib import Path
from typing import List, Dict, Optional, Literal, Any
from datetime import datetime

from agentic_consult.customers import get_active_customers_root, find_customer_by_id

logger = logging.getLogger(__name__)

def get_issues_dir(customer_slug: str) -> Path:
    """Get the root issues directory for a customer."""
    root = get_active_customers_root()
    return root / customer_slug / 'issues'

def list_issues(customer_slug: str, status: Literal['open', 'resolved', 'all'] = 'open') -> List[Dict[str, Any]]:
    """
    List issues for a specific customer.
    
    Args:
        customer_slug: The customer identifier.
        status: Filter by status ('open', 'resolved', 'all').
        
    Returns:
        List of issue dicts: {name, path, status, modified_time}
    """
    issues_root = get_issues_dir(customer_slug)
    if not issues_root.exists():
        return []

    results = []
    
    # Define paths to scan based on status request
    scan_targets = []
    if status in ['open', 'all']:
        scan_targets.append(('open', issues_root / 'open'))
        # Legacy: Check root for unsorted active issues
        scan_targets.append(('open', issues_root)) 
        
    if status in ['resolved', 'all']:
        scan_targets.append(('resolved', issues_root / 'resolved'))

    seen_names = set()

    for state, path in scan_targets:
        if not path.exists():
            continue
            
        for item in path.iterdir():
            if item.is_file() and not item.name.startswith('.'):
                # Avoid duplicates if scanning root + open (though users should migrate)
                # And avoid scanning subdirectories (like 'open' inside 'root')
                if item.name in seen_names:
                    continue
                
                seen_names.add(item.name)
                
                results.append({
                    "name": item.name,
                    "path": str(item),
                    "status": state,
                    "modified_time": item.stat().st_mtime
                })

    # Sort by modification time (newest first)
    results.sort(key=lambda x: x['modified_time'], reverse=True)
    return results

def create_issue(customer_slug: str, title: str, content: str = "") -> Dict[str, Any]:
    """Create a new issue in the 'open' folder."""
    issues_root = get_issues_dir(customer_slug)
    target_dir = issues_root / 'open'
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # Sanitize filename
    safe_title = "".join([c if c.isalnum() or c in ('-','_') else '_' for c in title]).lower()
    filename = f"{safe_title}.md"
    file_path = target_dir / filename
    
    if not content.startswith("#"):
        content = f"# {title}\n\n{content}"
        
    with open(file_path, 'w') as f:
        f.write(content)
        
    return {
        "name": filename,
        "path": str(file_path),
        "status": "open"
    }

def resolve_issue(customer_slug: str, filename: str) -> Dict[str, Any]:
    """Move an issue from open (or root) to resolved."""
    issues_root = get_issues_dir(customer_slug)
    resolved_dir = issues_root / 'resolved'
    resolved_dir.mkdir(parents=True, exist_ok=True)
    
    # Check open folder first
    source = issues_root / 'open' / filename
    if not source.exists():
        # Check root (legacy)
        source = issues_root / filename
        
    if not source.exists():
        raise FileNotFoundError(f"Issue '{filename}' not found in open or root.")
        
    destination = resolved_dir / filename
    source.rename(destination)
    
    return {
        "name": filename,
        "path": str(destination),
        "status": "resolved"
    }


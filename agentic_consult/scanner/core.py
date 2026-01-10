import os
import sys
import yaml
from pathlib import Path
from typing import List, Dict, Any
from collections import defaultdict

from agentic_consult.customers import get_active_customers_root, _parse_customer_yaml
from agentic_consult.scanner import scan_target, get_staged_files, get_disk_files, check_git_identity
from agentic_consult.config import load_app_config

def run_scan(path=".", include_ignored=False, author_check_fresh_only=False) -> Dict[str, Any]:
    """
    Runs a pre-commit scan for sensitive data in the specified path.
    
    Args:
        path: The directory or file path to scan.
        include_ignored: Whether to scan files ignored by git.
        author_check_fresh_only: Whether to focus only on recent/unpushed history.

    Returns:
        A dictionary containing the scan results, including a list of all
        findings categorized by type (e.g., 'email', 'drive_id').
    """
    # 1. Load Patterns for ALL Customers
    patterns = {}
    customers_checked = []
    
    root = get_active_customers_root()
    if root.exists():
        for d in root.iterdir():
            if d.is_dir():
                c_yaml = d / "customer.yaml"
                if c_yaml.exists():
                    try:
                        config = _parse_customer_yaml(c_yaml)
                        c_name = config.get('name')
                        c_slug = config.get('slug')
                        
                        customers_checked.append({'name': c_name, 'slug': c_slug})
                        
                        if c_name: patterns[c_name] = {'type': 'name', 'customer': c_name}
                        if c_slug: patterns[c_slug] = {'type': 'slug', 'customer': c_name}
                        
                        drive_id = config.get('drive_folder_id')
                        if drive_id: patterns[drive_id] = {'type': 'drive_id', 'customer': c_name}
                        
                        for k in config.get('keywords', []):
                            patterns[k] = {'type': 'keyword', 'customer': c_name}
                            
                    except Exception:
                        pass

    # Load allowed emails from internal config
    app_config = load_app_config()
    allowed_emails = app_config.get('precommit', {}).get('allowed_emails', [])
    fresh_days = app_config.get('precommit', {}).get('fresh_threshold_days', 3)
            
    local_user = os.environ.get("USER") or os.environ.get("USERNAME")
    if local_user:
        patterns[local_user] = {'type': 'local_user', 'customer': 'system'}

    staged_files = get_staged_files()
    disk_files = get_disk_files(path, include_ignored)
    
    # Aggregate results
    results = defaultdict(list)
    
    files_to_scan = []
    if staged_files:
        files_to_scan.extend([(f, True) for f in staged_files])
    if disk_files:
        files_to_scan.extend([(f, False) for f in disk_files])
        
    for f_path, is_staged in files_to_scan:
        findings = scan_target(f_path, patterns, staged=is_staged, allowed_emails=allowed_emails)
        for f in findings:
            cat = f.get('type', 'unknown')
            msg = f.get('msg', str(f))
            
            source = f"{f_path} {'(staged)' if is_staged else ''}"
            line = f.get('line')
            issue_str = f"{source}:{line} - {msg}" if line else f"{source} - {msg}"
            
            results[cat].append(issue_str)

    # Git Identity Check
    identity_issues = check_git_identity(path, only_fresh=only_fresh, fresh_days=fresh_days)
    if identity_issues:
        results['git_identity'].extend(identity_issues)

    # Prepare final summary
    summary = {
        'findings': dict(results),
        'customers_checked': customers_checked,
        'allowed_emails_count': len(allowed_emails),
        'failed': any(results.values())
    }
    
    return summary

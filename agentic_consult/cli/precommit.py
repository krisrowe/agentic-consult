import click
import os
import sys
import yaml
from pathlib import Path
from typing import List, Dict, Any
from collections import defaultdict

from agentic_consult.customers import get_active_customers_root, _parse_customer_yaml
from agentic_consult.scanner import scan_target, get_staged_files, get_disk_files, check_git_identity

CHECK_CATEGORIES = {
    "email": "Email Addresses",
    "drive_id": "Drive IDs",
    "keyword": "Sensitive Keywords",
    "ticket_id": "Ticket IDs",
    "filename": "Sensitive Filenames",
    "git_identity": "Git Identity",
}

def print_check_result(name: str, issues: List[str], verbose: bool):
    """Prints the status line for a check."""
    status = "✅" if not issues else "❌"
    
    if verbose or issues:
        click.echo(f"{status} {name}")
        
    if issues:
        for issue in issues:
            click.echo(f"   - {issue}")

@click.command()
@click.option('--include-ignored', is_flag=True, help="Scan ignored files too.")
@click.option('--verbose', '-v', is_flag=True, help="Show detailed status of all checks.")
@click.argument('path', default='.', type=click.Path(exists=True))
def precommit(include_ignored, verbose, path):
    """Scans files for sensitive data."""
    
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
                        
                        # Anonymized label for report
                        cust_label = f"Customer '{c_name}'"
                        customers_checked.append({'name': c_name, 'slug': c_slug, 'label': cust_label})
                        
                        if c_name: patterns[c_name] = {'type': 'name', 'customer': c_name}
                        if c_slug: patterns[c_slug] = {'type': 'slug', 'customer': c_name}
                        
                        drive_id = config.get('drive_folder_id')
                        if drive_id: patterns[drive_id] = {'type': 'drive_id', 'customer': c_name}
                        
                        for k in config.get('keywords', []):
                            patterns[k] = {'type': 'keyword', 'customer': c_name}
                            
                    except Exception:
                        pass

    # Load app.yaml allowed emails
    allowed_emails = []
    app_yaml_path = Path("app.yaml")
    if app_yaml_path.exists():
        try:
            with open(app_yaml_path, 'r') as f:
                app_config = yaml.safe_load(f) or {}
                allowed_emails = app_config.get('precommit', {}).get('allowed_emails', [])
        except Exception:
            pass
            
    local_user = os.environ.get("USER") or os.environ.get("USERNAME")
    if local_user:
        patterns[local_user] = {'type': 'local_user', 'customer': 'system'}

    staged_files = get_staged_files()
    disk_files = get_disk_files(path, include_ignored)
    
    # Aggregate results
    results = defaultdict(list)
    customer_issues = defaultdict(list)
    
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
            cust = f.get('customer')
            
            source = f"{f_path} {'(staged)' if is_staged else ''}"
            line = f.get('line')
            issue_str = f"{source}:{line} - {msg}" if line else f"{source} - {msg}"
            
            results[cat].append(issue_str)
            
            if cust and cust != 'system':
                customer_issues[cust].append(issue_str)

    # Git Identity Check
    identity_issues = check_git_identity(path)
    if identity_issues:
        results['git_identity'].extend(identity_issues)

    if verbose:
        click.echo("\nRunning Pre-commit Checks...")
        click.echo("----------------------------")

    failed_checks = 0
    # General Checks
    for cat_key, cat_name in CHECK_CATEGORIES.items():
        issues = results.get(cat_key, [])
        
        display_name = cat_name
        if cat_key == 'email':
            allowlist_count = len(allowed_emails)
            if allowlist_count > 0:
                display_name = f"{cat_name} ({allowlist_count} configured to be ignored)"
        
        if issues:
            failed_checks += 1
        print_check_result(display_name, issues, verbose)

    # Customer Specific Checks
    failed_customers = 0
    for i, cust in enumerate(customers_checked):
        issues = customer_issues.get(cust['name'], [])
        if issues:
            failed_customers += 1
        print_check_result(f"{cust['label']} (Conf: {cust['slug']})", issues, verbose)

    # Summary
    total_checks = len(CHECK_CATEGORIES) + len(customers_checked)
    passed_checks = total_checks - (failed_checks + failed_customers)
    summary_color = "green" if (failed_checks + failed_customers) == 0 else "red"
    
    if verbose or (failed_checks + failed_customers) > 0:
        click.echo("-" * 30)
    
    click.secho(f"Summary: {passed_checks}/{total_checks} checks passed", fg=summary_color, bold=True)
    
    if (failed_checks + failed_customers) > 0:
        sys.exit(1)
    sys.exit(0)
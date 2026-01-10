import click
import sys
from typing import List, Dict, Any
from collections import defaultdict

from agentic_consult.scanner.core import run_scan

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
@click.option('--author-check-fresh-only', is_flag=True, help="Only scan unpushed or recent commits for identity.")
@click.option('--verbose', '-v', is_flag=True, help="Show detailed status of all checks.")
@click.argument('path', default='.', type=click.Path(exists=True))
def precommit(include_ignored, author_check_fresh_only, verbose, path):
    """Scans files for sensitive data."""
    
    scan_results = run_scan(path=path, include_ignored=include_ignored, author_check_fresh_only=author_check_fresh_only)
    
    findings = scan_results['findings']
    customers_checked = scan_results['customers_checked']
    
    if verbose:
        click.echo("\nRunning Pre-commit Checks...")
        click.echo("----------------------------")

    failed_checks = 0
    # General Checks
    for cat_key, cat_name in CHECK_CATEGORIES.items():
        issues = findings.get(cat_key, [])
        
        display_name = cat_name
        if cat_key == 'email':
            allowlist_count = scan_results['allowed_emails_count']
            if allowlist_count > 0:
                display_name = f"{cat_name} ({allowlist_count} configured to be ignored)"
        
        if issues:
            failed_checks += 1
        print_check_result(display_name, issues, verbose)

    # Summary
    total_checks = len(CHECK_CATEGORIES)
    passed_checks = total_checks - failed_checks
    summary_color = "green" if not scan_results['failed'] else "red"
    
    if verbose or scan_results['failed']:
        click.echo("-" * 30)
    
    click.secho(f"Summary: {passed_checks}/{total_checks} checks passed", fg=summary_color, bold=True)
    
    if scan_results['failed']:
        sys.exit(1)
    sys.exit(0)

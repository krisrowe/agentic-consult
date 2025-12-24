import click
import os
import sys

from agentic_consult.customers import load_customer_config
from agentic_consult.scanner import scan_target, get_staged_files, get_disk_files, check_git_identity

@click.command()
@click.option('--include-ignored', is_flag=True, help="Scan ignored files too.")
@click.argument('path', default='.', type=click.Path(exists=True))
def precommit(include_ignored, path):
    """Scans files for sensitive data."""
    config = load_customer_config()
    patterns = {}
    local_user = os.environ.get("USER") or os.environ.get("USERNAME")
    if local_user:
        patterns[local_user] = {'type': 'local_user', 'customer': 'system'}
    if config:
        c_name = config.get('name')
        if c_name: patterns[c_name] = {'type': 'name', 'customer': c_name}
        c_slug = config.get('slug')
        if c_slug: patterns[c_slug] = {'type': 'slug', 'customer': c_name}
        drive_id = config.get('drive_folder_id')
        if drive_id: patterns[drive_id] = {'type': 'drive_id', 'customer': c_name}
        for k in config.get('keywords', []):
            patterns[k] = {'type': 'keyword', 'customer': c_name}

    staged = get_staged_files()
    disk = get_disk_files(path, include_ignored)
    all_issues = {}
    if staged:
        for f in staged:
            issues = scan_target(f, patterns, staged=True)
            if issues: all_issues[f"{f} (staged)"] = issues
    if disk:
        for f in disk:
            issues = scan_target(f, patterns, staged=False)
            if issues: all_issues[f"{f} (disk)"] = issues

    # 3. Check Git Identity
    identity_issues = check_git_identity(path)
    if identity_issues:
        all_issues["Git Identity"] = identity_issues

    if all_issues:
        click.echo("\nBlocked: Potential sensitive data or identity issues found.\n", err=True)
        for f, errs in all_issues.items():
            click.echo(f"Source: {f}", err=True)
            for e in errs: click.echo(f"  - {e}", err=True)
        sys.exit(1)
    else:
        click.echo("No sensitive matches found.")
        sys.exit(0)

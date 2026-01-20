import click
import sys
import time
from rich.console import Console

from agentic_consult.sdk.scanner import run_scan, CheckResult

# Main console for stdout
console = Console()
# Error console for stderr
error_console = Console(stderr=True)

def get_status_icon(result: CheckResult):
    """Returns icon and color for a check result."""
    if result.skipped:
        return "⏭️ ", "yellow"
    if result.passed:
        return "✅", "green"
    return "❌", "red"

def print_check_line(result: CheckResult, current: int, total: int, verbose: bool = False):
    """Print a single line result in the format: [#/#] Name Icon Detail"""
    icon, color = get_status_icon(result)
    
    # Determine details
    details = result.info or ""
    if result.skipped and not details:
        details = "No configuration found"
    elif not result.passed and not result.skipped and result.findings:
        details = f"{len(result.findings)} findings"

    # Format the line
    line = f"[dim][{current}/{total}][/dim] [bold]{result.name:<30}[/bold] {icon} [dim]{details}[/dim]"
    console.print(line)

    # Show findings if failed
    if not result.passed and not result.skipped:
        limit = None if verbose else 5
        for finding in result.findings[:limit]:
            console.print(f"      [red]↳[/red] [dim]{finding}[/dim]")
        if not verbose and len(result.findings) > 5:
            console.print(f"      [dim]... and {len(result.findings) - 5} more (use -v to see all)[/dim]")

@click.command()
@click.option('--deep', is_flag=True, help="Also scan git history (slower).")
@click.option('--verbose', '-v', is_flag=True, help="Show detailed status of all checks.")
@click.argument('path', default='.', type=click.Path(exists=True))
def precommit(deep, verbose, path):
    """Scans repository for sensitive data before commit.

    By default, scans uncommitted changes (staged, unstaged, untracked).
    Use --deep to also scan full git history.
    """
    if verbose:
        console.print("\n[bold blue]🔍 Pre-commit Scan[/bold blue]")
        console.print("━" * 40)

    start_time = time.time()
    
    report = run_scan(
        repo_path=path,
        deep=deep,
        on_check_complete=lambda r, c, t: print_check_line(r, c, t, verbose) if verbose else None
    )
    
    duration = time.time() - start_time

    if not verbose:
        # In non-verbose mode, ONLY show failures or unexpected errors
        for i, check in enumerate(report.checks, start=1):
            is_failure = not check.passed and not check.skipped
            if is_failure:
                # Header for first failure
                has_previous_failure = any(not c.passed and not c.skipped for c in report.checks[:i-1])
                if not has_previous_failure:
                     console.print("\n[bold red]🔍 Scan Issues Found:[/bold red]")
                print_check_line(check, i, len(report.checks), verbose)

    # Final Summary to stderr
    total = len(report.checks)
    passed = report.passed_count
    failed = report.failed_count
    
    if report.failed:
        status_line = f"[bold red]❌ {passed}/{total} checks PASSED, {failed} FAILED ({duration:.1f}s)[/bold red]"
    else:
        status_line = f"[bold green]✅ {passed}/{total} checks PASSED ({duration:.1f}s)[/bold green]"
    
    # Always print to stderr
    error_console.print(status_line)

    if report.failed:
        sys.exit(1)
    else:
        sys.exit(0)

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


def print_check_line(result: CheckResult, current: int, total: int, show_table: bool = True):
    """Print a single line result in the format: [#/#] Name Icon Detail"""
    # Only print passed/skipped items if we are showing the full table
    if show_table or (not result.passed and not result.skipped):
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
            for finding in result.findings[:5]:
                console.print(f"      [red]↳[/red] [dim]{finding}[/dim]")
            if len(result.findings) > 5:
                console.print(f"      [dim]... and {len(result.findings) - 5} more[/dim]")


@click.command()
@click.option('--deep', is_flag=True, help="Also scan git history (slower).")
@click.option('--summary', '-s', is_flag=True, help="Show only failures and final summary (hide table).")
@click.option('--verbose', '-v', is_flag=True, help="Show detailed status of all checks (default unless --summary).")
@click.option('--only', 'only_check', help="Run only this check module (e.g., ssn_ein, amounts, devws).")
@click.option('--untracked', is_flag=True, help="Also scan untracked files (off by default).")
@click.argument('path', default='.', type=click.Path(exists=True))
def precommit(deep, summary, verbose, only_check, untracked, path):
    """Scans repository for sensitive data before commit.

    By default, scans staged and unstaged changes only.
    Use --untracked to also scan untracked files.
    Use --deep to also scan full git history.
    """
    show_table = not summary

    if show_table:
        console.print("\n[bold blue]🔍 Pre-commit Scan[/bold blue]")
        console.print("━" * 40)

    start_time = time.time()

    report = run_scan(
        repo_path=path,
        deep=deep,
        only_check=only_check,
        include_untracked=untracked,
        on_check_complete=lambda r, c, t: print_check_line(r, c, t, show_table=show_table)
    )

    duration = time.time() - start_time

    # Final Summary to stderr
    total = len(report.checks)
    passed = report.passed_count
    failed = report.failed_count

    if show_table:
        console.print("━" * 40)

    if report.failed:
        status_line = f"[bold red]❌ {passed}/{total} checks PASSED, {failed} FAILED ({duration:.1f}s)[/bold red]"
    else:
        status_line = f"[bold green]✅ {passed}/{total} checks PASSED ({duration:.1f}s)[/bold green]"

    error_console.print(status_line)

    if report.failed:
        sys.exit(1)
    else:
        sys.exit(0)


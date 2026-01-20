import click
import sys

from agentic_consult.sdk.scanner import run_scan, CheckResult


def print_check_progress(result: CheckResult, current: int, total: int):
    """Print check result as it completes (streaming output)."""
    if result.skipped:
        status = "⏭️ "
        color = "yellow"
    elif result.passed:
        status = "✅"
        color = "green"
    else:
        status = "❌"
        color = "red"

    click.secho(f"[{current}/{total}] {status} {result.name}", fg=color)

    if not result.passed and not result.skipped:
        for finding in result.findings[:5]:
            click.echo(f"      - {finding}")
        if len(result.findings) > 5:
            click.echo(f"      ... and {len(result.findings) - 5} more")


@click.command()
@click.option('--deep', is_flag=True, help="Also scan git history (slower).")
@click.option('--verbose', '-v', is_flag=True, help="Show detailed status of all checks.")
@click.option('--only', 'only_check', help="Run only this check module (e.g., ssn_ein, amounts, devws).")
@click.argument('path', default='.', type=click.Path(exists=True))
def precommit(deep, verbose, only_check, path):
    """Scans repository for sensitive data before commit.

    By default, scans uncommitted changes (staged, unstaged, untracked).
    Use --deep to also scan full git history.
    """
    click.echo("\n🔍 Pre-commit Scan")
    click.echo("=" * 40)

    report = run_scan(
        repo_path=path,
        deep=deep,
        only_check=only_check,
        on_check_complete=print_check_progress if verbose else None
    )

    if not verbose:
        for check in report.checks:
            if not check.passed and not check.skipped:
                click.secho(f"  ❌ {check.name}", fg="red")
                for finding in check.findings[:3]:
                    click.echo(f"      - {finding}")
                if len(check.findings) > 3:
                    click.echo(f"      ... and {len(check.findings) - 3} more")

        if not report.failed:
            click.secho("  ✅ All checks passed", fg="green")

    click.echo("\n" + "=" * 40)

    if report.failed:
        click.secho(f"❌ FAILED: {report.failed_count} check(s) failed", fg="red", bold=True)
        sys.exit(1)
    else:
        click.secho(f"✅ PASSED: All checks passed", fg="green", bold=True)
        sys.exit(0)

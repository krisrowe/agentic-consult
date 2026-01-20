"""CLI for email operations."""

import click
import json


@click.group()
def email():
    """Email processing commands."""
    pass


@email.group()
def triage():
    """Email triage commands."""
    pass


@triage.command("stats")
@click.option("--sample-size", default=20, help="Number of active emails to sample for action breakdown")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", help="Output format")
def triage_stats(sample_size: int, output_format: str):
    """Show email triage statistics."""
    from rich.console import Console
    from rich.table import Table
    from ..email.triage import get_triage_stats

    result = get_triage_stats(sample_size=sample_size)

    if output_format == "json":
        click.echo(json.dumps(result, indent=2))
        return

    console = Console()

    if "error" in result:
        console.print(f"[red]Error:[/red] {result['error']}")
        if "path" in result:
            console.print(f"Path: {result['path']}")
        return

    emails = result.get("emails", {})

    table = Table(title="Email Triage Stats")
    table.add_column("State", style="cyan")
    table.add_column("Count", justify="right")
    table.add_column("Date Range")

    for state in ["fetched", "analyzed", "resolved", "active"]:
        data = emails.get(state, {})
        count = str(data.get("count", 0))
        date_range = ""
        if data.get("start"):
            date_range = f"{data['start']} → {data.get('end', '?')}"
        table.add_row(state.capitalize(), count, date_range)

    console.print(table)

    # Sample breakdown for active
    active = emails.get("active", {})
    sample = active.get("sample")
    if sample and sample.get("size", 0) > 0:
        console.print(f"\n[dim]Sample ({sample['size']} active):[/dim]")
        for key, val in sample.items():
            if key != "size":
                console.print(f"  {key}: {val}")

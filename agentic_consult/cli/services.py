"""CLI for background services."""

import click
import logging
from email_archive import EmailStore
from ..email.analyzer import EmailAnalyzer, GeminiProvider

@click.group()
def services():
    """Manage background services."""
    pass

@services.command("analyze")
@click.option("--limit", type=int, help="Max emails to process (SDK default if omitted).")
@click.option("--lookback", type=int, help="Days to look back (SDK default if omitted).")
@click.option("--model", help="Gemini model override.")
@click.option("--verbose", is_flag=True, help="Enable debug logging.")
def services_analyze(limit, lookback, model, verbose):
    """Run one cycle of the asynchronous email analyzer."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    store = EmailStore()
    provider = GeminiProvider(model=model) if model else None
    analyzer = EmailAnalyzer(store, provider=provider)
    
    # We pass explicit None if not provided to allow EmailAnalyzer to use class-level defaults
    click.echo(f"Starting analysis loop...")
    result = analyzer.process_queue(lookback_days=lookback, limit=limit)
    
    processed = result.get("processed", 0)
    
    if processed > 0:
        click.secho(f"✅ Success: Processed {processed} emails.", fg="green")
    else:
        click.secho(f"Idle: No pending emails found.", fg="yellow")
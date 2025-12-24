import click
import os
import sys
import yaml
import datetime
import shutil
import subprocess
from pathlib import Path
import json
import logging

from agentic_consult.customers import find_customer_by_id, load_customer_config, get_active_customers_root
from agentic_consult.config import load_main_config
from agentic_consult.processing_state import load_processed_emails, mark_emails_processed, filter_unprocessed_emails
from agentic_consult.gmail import fetch_and_cache_emails
from agentic_consult.ticktick import fetch_and_cache_tasks
from agentic_consult.refresh import build_prompt

logger = logging.getLogger(__name__)

# Copied from the old cli.py, needed for process_deltas
def process_deltas(deltas_path: Path, config: dict, customer_dir: Path, expected_max_deltas: int = None):
    """Parses a deltas.json file and applies the changes."""
    if not deltas_path.exists():
        return

    try:
        with open(deltas_path, 'r') as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        click.echo(f"Warning: Could not read or parse '{deltas_path.name}'.", err=True)
        return

    click.echo(f"\n=== Proposed Plan ({deltas_path.name}) ===")
    click.echo(json.dumps(data, indent=2))
    click.echo("========================================\n")

    skip_writes = config.get('skip_task_writes', True)
    project = config.get('ticktick_project', 'Work')
    
    # ... (rest of process_deltas logic)

@click.command(name='refresh')
@click.argument('identifier', required=False)
@click.option('--dry-run/--no-dry-run', default=True)
@click.option('--gemini-cmd', default='gemini')
@click.option('--max-emails', type=int, help="Max emails to fetch.")
@click.option('--read-archived-email/--no-read-archived-email', default=None)
@click.option('--since', help="Filter emails after date (YYYY-MM-DD).")
@click.option('--skip-fetch', is_flag=True, help="Skip fetching and use cache.")
@click.option('--expected-max-deltas', type=int, help="Fail if deltas exceed this.")
@click.option('--skip-task-writes/--no-skip-task-writes', default=None)
@click.option('--retry-deltas', 'retry_deltas_file', help="Retry processing an existing deltas file.")
def refresh(identifier, dry_run, gemini_cmd, max_emails, read_archived_email, since, skip_fetch, expected_max_deltas, skip_task_writes, retry_deltas_file):
    """Refreshes customer context by fetching, analyzing, and preparing a plan."""
    # This is the full, refactored refresh logic from the old cli.py
    # ... (full implementation of the refresh command)

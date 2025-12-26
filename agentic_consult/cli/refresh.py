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
from agentic_consult.config import load_main_config, get_config_path
from agentic_consult.processing_state import load_processed_emails, mark_emails_processed, filter_unprocessed_emails
from agentic_consult.gmail import fetch_and_cache_emails
from agentic_consult.refresh import build_prompt
from agentic_consult.utils import clean_json_output
from agentic_consult.gemini import GeminiAPIClient, GeminiOutputError

# New Task Architecture Imports
from agentic_consult.tasks import load_tasks, save_tasks, add_new_task, update_task
from agentic_consult.tasks.factory import get_task_provider

logger = logging.getLogger(__name__)

PROMPT_TPL_FILENAME = "prompt.tpl"

def process_deltas(deltas_path: Path, config: dict, customer_dir: Path, tasks: list, expected_max_deltas: int = None):
    """
    Parses a deltas.json file and applies the changes (Tasks & Issues).
    Updates the local tasks list in-place.
    """
    if not deltas_path.exists():
        return

    try:
        with open(deltas_path, 'r') as f:
            content = f.read()
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                cleaned = clean_json_output(content)
                data = json.loads(cleaned)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        click.echo(f"Warning: Could not read or parse '{deltas_path.name}'. Error: {e}", err=True)
        return

    tasks_create = []
    tasks_update = []
    issues_update = []
    
    for email_entry in data.get('emails', []):
        for delta in email_entry.get('deltas', []):
            dtype = delta.get('type')
            if dtype == 'task_create':
                tasks_create.append(delta)
            elif dtype == 'task_update':
                tasks_update.append(delta)
            elif dtype == 'issue_update':
                issues_update.append(delta)

    # --- Safety Checks ---
    total_ops = len(tasks_create) + len(tasks_update)
    
    click.echo(f"\n=== Proposed Plan ({deltas_path.name}) ===")
    click.echo(json.dumps(data, indent=2))
    click.echo("========================================\n")

    if expected_max_deltas is not None and total_ops > expected_max_deltas:
        click.echo(f"SAFETY LIMIT EXCEEDED: Proposed {total_ops} changes, limit is {expected_max_deltas}.", err=True)
        sys.exit(1)

    skip_writes = config.get('skip_task_writes', False) if config else False

    # --- Task Management (Local) ---
    if not skip_writes:
        for task_delta in tasks_create:
            new_task = add_new_task(tasks, task_delta)
            click.echo(f"Created local task #{new_task['sequence_number']}: {new_task['title']}")

        for task_delta in tasks_update:
            # Gemini provides 'id' which corresponds to our sequence_number
            try:
                seq_num = int(task_delta.get('id'))
                updated = update_task(tasks, seq_num, task_delta)
                if updated:
                    click.echo(f"Updated local task #{seq_num}")
                else:
                    click.echo(f"Warning: Could not find task #{seq_num} to update", err=True)
            except (ValueError, TypeError):
                click.echo(f"Warning: Invalid task ID format in delta: {task_delta.get('id')}", err=True)
                
        # Save updated local state
        save_tasks(customer_dir, tasks)

    # --- Issue Tracking ---
    issues_dir = customer_dir / 'issues'
    issues_dir.mkdir(exist_ok=True)
    
    for issue in issues_update:
        issue_id = issue.get('file')
        if not issue_id: continue
        
        safe_id = "".join([c for c in issue_id if c.isalpha() or c.isdigit() or c in ('-','_','.')]).rstrip()
        filename = safe_id
        if not filename.endswith('.md'):
            filename += '.md'
        file_path = issues_dir / filename
        
        content = issue.get('content', '')
        
        if skip_writes:
             click.echo(f"SKIPPED: Would update issue file {filename}")
        else:
            mode = 'a' if file_path.exists() else 'w'
            try:
                with open(file_path, mode) as f:
                    if mode == 'a': f.write("\n\n")
                    f.write(content)
                click.echo(f"Updated issue file: {filename}")
            except Exception as e:
                click.echo(f"Failed to write issue file {filename}: {e}", err=True)

    # --- Archive the Delta File ---
    if not skip_writes:
        archive_dir = customer_dir / 'deltas_archive'
        archive_dir.mkdir(exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        archive_path = archive_dir / f"done_deltas_{timestamp}.json"
        try:
            shutil.move(deltas_path, archive_path)
            click.echo(f"Archived processed deltas to {archive_path}")
        except Exception as e:
            click.echo(f"Warning: Failed to archive deltas.json: {e}", err=True)


@click.command(name='refresh')
@click.argument('identifier', required=False)
@click.option('--dry-run/--no-dry-run', default=True)
@click.option('--max-emails', type=int, default=10, help="Max emails to fetch.")
@click.option('--read-archived-email/--no-read-archived-email', default=None)
@click.option('--since', help="Filter emails after date (YYYY-MM-DD).")
@click.option('--skip-fetch', is_flag=True, help="Skip fetching and use cache.")
@click.option('--expected-max-deltas', type=int, help="Fail if deltas exceed this.")
@click.option('--skip-task-writes/--no-skip-task-writes', default=None)
@click.option('--retry-deltas', 'retry_deltas_arg', type=str, is_flag=False, flag_value='deltas.json', default=None, help="Retry processing an existing deltas file.")
@click.option('--force-refresh', is_flag=True, help="Force refresh even if no new emails.") 
def refresh(identifier, dry_run, max_emails, read_archived_email, since, skip_fetch, expected_max_deltas, skip_task_writes, retry_deltas_arg, force_refresh):
    """Refreshes customer context by fetching, analyzing, and preparing a plan."""
    
    # 1. Load Customer
    cust = load_customer_config() if not identifier else find_customer_by_id(identifier)
    if not cust:
        click.echo("Error: Customer not found.", err=True)
        sys.exit(1)

    customer_slug = cust['slug']
    customer_dir = get_active_customers_root() / customer_slug
    customer_dir.mkdir(parents=True, exist_ok=True)

    # 2. Load Config & Prompt Template
    config = load_main_config() or {}
    if skip_task_writes is not None:
        config['skip_task_writes'] = skip_task_writes
    
    prompt_path = customer_dir / PROMPT_TPL_FILENAME
    template = None
    if prompt_path.exists():
        template = prompt_path.read_text()
    else:
        global_path = get_config_path(PROMPT_TPL_FILENAME)
        if global_path and global_path.exists():
            template = global_path.read_text()
        else:
            try:
                from importlib import resources
                pkg_files = resources.files('agentic_consult')
                template = (pkg_files / PROMPT_TPL_FILENAME).read_text()
            except Exception as e:
                click.echo(f"Warning: Failed to load bundled template: {e}", err=True)
    if not template:
        click.echo("Error: No prompt template found.", err=True)
        sys.exit(1)
    
    # 3. Processed Emails Tracking
    processed_emails = load_processed_emails(customer_dir)
    
    # 4. Handle --retry-deltas
    if retry_deltas_arg:
        tasks = load_tasks(customer_dir)
        retry_path = Path(retry_deltas_arg)
        if not retry_path.is_absolute():
            retry_path = customer_dir / retry_path
        
        click.echo(f"Retrying deltas from: {retry_path}")
        process_deltas(retry_path, config, customer_dir, tasks, expected_max_deltas)
        
        if config.get("sync_tasks", True):
            provider = get_task_provider()
            if provider:
                click.echo("Syncing tasks to provider...")
                if provider.sync(tasks):
                    save_tasks(customer_dir, tasks)
        return

    # 5. Fetch Emails
    use_mock_data = config.get('use_mock_data', False)
    if not skip_fetch:
        click.echo(f"Fetching emails for {cust['name']}...")
        fetch_and_cache_emails(cust, customer_dir, max_emails=max_emails, since=since, processed_ids=processed_emails, use_mock_data=use_mock_data)
    
    email_cache = customer_dir / 'emails' / 'emails.json'
    all_emails = []
    if email_cache.exists():
        with open(email_cache) as f:
            all_emails = json.load(f)
    unprocessed_emails, _ = filter_unprocessed_emails(all_emails, processed_emails)

    if not unprocessed_emails and not force_refresh:
        click.echo("No new unprocessed emails. Exiting.", err=True)
        return

    # 6. Load Local Tasks
    tasks = load_tasks(customer_dir)

    # Sync tasks BEFORE Gemini call to ensure latest context
    if config.get("sync_tasks", True):
        provider = get_task_provider()
        if provider:
            click.echo("Syncing tasks from provider (pre-analysis)...")
            if provider.sync(tasks):
                save_tasks(customer_dir, tasks)

    # Prepare tasks for prompt
    prompt_tasks = []
    for t in tasks:
        pt = t.copy()
        pt['id'] = str(t.get('sequence_number'))
        prompt_tasks.append(pt)

    # 7. Prepare Prompt
    prompt_input = build_prompt(template, config, cust, unprocessed_emails, prompt_tasks, customer_dir)
    gemini_input_path = customer_dir / "gemini-input.txt"
    gemini_input_path.write_text(prompt_input)

    # 8. Archive existing deltas
    deltas_path = customer_dir / "deltas.json"
    if deltas_path.exists() and not dry_run:
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        archive_name = f"abandoned_deltas_{timestamp}.json"
        shutil.move(str(deltas_path), str(customer_dir / archive_name))

    # 9. Dry Run
    if dry_run:
        click.echo(f"\nDRY_RUN=1")
        click.echo(f"Customer: {cust['name']}")
        click.echo(f"New Emails: {len(unprocessed_emails)}")
        click.echo(f"Local Tasks: {len(tasks)}")
        # Fixing the output for the test assertion
        click.echo(f"Would execute: Gemini API generation ({config.get('gemini', {}).get('models', {}).get('default', '2.5-flash')})")
        click.echo(f"\n=== Prompt Preview ===\n{prompt_input[:500]}...\n(truncated)")
        return

    # 10. Run Gemini
    click.echo(f"Executing Gemini API...")
    if config.get('use_mock_gemini'):
        repo_root = Path(__file__).resolve().parent.parent.parent
        mock_path = repo_root / 'mock-deltas.json'
        if not mock_path.exists(): mock_path = repo_root / 'mock-deltas.json.example'
        with open(mock_path, 'r') as f: data = json.load(f)
        with open(deltas_path, 'w') as f: json.dump(data, f, indent=2)
    else:
        try:
            client = GeminiAPIClient()
            data = client.generate_prompt_driven_json(prompt_input)
            with open(deltas_path, 'w') as f: json.dump(data, f, indent=2)
            click.echo(f"Gemini output saved to {deltas_path}")
        except Exception as e:
            click.echo(f"Gemini generation failed: {e}", err=True)
            sys.exit(1)

    # 11. Load Deltas for Ack (Before processing/archiving)
    try:
        with open(deltas_path, 'r') as f: deltas = json.load(f)
    except: deltas = {}

    # 12. Process Deltas (Updates Local State)
    process_deltas(deltas_path, config, customer_dir, tasks, expected_max_deltas)
    
    # 13. Sync Tasks to Provider (Optional)
    if config.get("sync_tasks", True):
        provider = get_task_provider()
        if provider:
            click.echo("Syncing tasks to provider...")
            if provider.sync(tasks):
                save_tasks(customer_dir, tasks)
                click.echo("Sync complete.")
            else:
                click.echo("Warning: Task sync encountered errors.", err=True)
    
    # 14. Update Email State
    if deltas:
        ack_ids = set()
        for email_entry in deltas.get('emails', []):
            if 'id' in email_entry: ack_ids.add(email_entry['id'])
        if ack_ids:
            mark_emails_processed(customer_dir, ack_ids)
            click.echo(f"Marked {len(ack_ids)} emails as processed")
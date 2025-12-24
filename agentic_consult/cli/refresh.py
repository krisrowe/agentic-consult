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
from agentic_consult.ticktick import fetch_and_cache_tasks
from agentic_consult.refresh import build_prompt

logger = logging.getLogger(__name__)

PROMPT_TPL_FILENAME = "prompt.tpl"

def process_deltas(deltas_path: Path, config: dict, customer_dir: Path, expected_max_deltas: int = None):
    """
    Parses a deltas.json file and applies the changes (Tasks & Issues).
    Recreated logic including safety checks, TickTick CLI integration, and issue file updates.
    """
    if not deltas_path.exists():
        return

    try:
        with open(deltas_path, 'r') as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        click.echo(f"Warning: Could not read or parse '{deltas_path.name}'.", err=True)
        return

    # --- 1. Safety Checks ---
    total_ops = 0
    if 'tasks' in data:
        total_ops += len(data['tasks'].get('create', []))
        total_ops += len(data['tasks'].get('update', []))
    # We could count issue updates too if desired, but usually tasks are the critical safety concern
    
    click.echo(f"\n=== Proposed Plan ({deltas_path.name}) ===")
    click.echo(json.dumps(data, indent=2))
    click.echo("========================================\n")

    if expected_max_deltas is not None and total_ops > expected_max_deltas:
        click.echo(f"SAFETY LIMIT EXCEEDED: Proposed {total_ops} changes, limit is {expected_max_deltas}.", err=True)
        sys.exit(1)

    skip_writes = config.get('skip_task_writes', False) if config else False
    project = config.get('ticktick_project', 'Work')

    # --- 2. Task Management (TickTick) ---
    tasks_data = data.get('tasks', {})
    
    # Create Tasks
    for task in tasks_data.get('create', []):
        title = task.get('title')
        if not title: continue
        
        cmd = ['ticktick', 'task', 'create', '--title', title, '--project', project]
        if task.get('content'):
            cmd.extend(['--content', task['content']])
        if task.get('priority'):
            cmd.extend(['--priority', str(task['priority'])])
            
        if skip_writes:
            click.echo(f"SKIPPED: Would run command: {' '.join(cmd)}")
        else:
            click.echo(f"Creating task: {title}")
            try:
                subprocess.run(cmd, check=True, capture_output=True)
            except subprocess.CalledProcessError as e:
                click.echo(f"Failed to create task '{title}': {e}", err=True)

    # Update Tasks
    for task in tasks_data.get('update', []):
        task_id = task.get('id')
        if not task_id: continue
        
        cmd = ['ticktick', 'tasks', 'update', task_id] # Note: 'tasks update' based on typical CLI, or 'task update'
        # Assuming we might map fields. For now, let's assume specific flags or just content
        if task.get('content'):
             cmd.extend(['--content', task['content']])
        
        if skip_writes:
            click.echo(f"SKIPPED: Would run command: {' '.join(cmd)}")
        else:
            click.echo(f"Updating task {task_id}")
            try:
                subprocess.run(cmd, check=True, capture_output=True)
            except subprocess.CalledProcessError as e:
                click.echo(f"Failed to update task '{task_id}': {e}", err=True)

    # --- 3. Issue Tracking ---
    issues_dir = customer_dir / 'issues'
    issues_dir.mkdir(exist_ok=True)
    
    for issue in data.get('issues', {}).get('update', []):
        issue_id = issue.get('id')
        if not issue_id: continue
        
        # Sanitize filename
        safe_id = "".join([c for c in issue_id if c.isalpha() or c.isdigit() or c in ('-','_')]).rstrip()
        filename = f"{safe_id}.md"
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

    # --- 4. Archive the Delta File ---
    if not skip_writes:
        # Move processed deltas to an archive folder to prevent re-processing
        archive_dir = customer_dir / 'deltas_archive'
        archive_dir.mkdir(exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        archive_path = archive_dir / f"deltas-{timestamp}.json"
        try:
            shutil.move(deltas_path, archive_path)
            click.echo(f"Archived processed deltas to {archive_path}")
        except Exception as e:
            click.echo(f"Warning: Failed to archive deltas.json: {e}", err=True)


@click.command(name='refresh')
@click.argument('identifier', required=False)
@click.option('--dry-run/--no-dry-run', default=True)
@click.option('--gemini-cmd', default='gemini')
@click.option('--max-emails', type=int, default=10, help="Max emails to fetch.")
@click.option('--read-archived-email/--no-read-archived-email', default=None)
@click.option('--since', help="Filter emails after date (YYYY-MM-DD).")
@click.option('--skip-fetch', is_flag=True, help="Skip fetching and use cache.")
@click.option('--expected-max-deltas', type=int, help="Fail if deltas exceed this.")
@click.option('--skip-task-writes/--no-skip-task-writes', default=None)
@click.option('--retry-deltas', 'retry_deltas_file', is_flag=True, help="Retry processing an existing deltas file.")
@click.option('--force-refresh', is_flag=True, help="Force refresh even if no new emails.") 
def refresh(identifier, dry_run, gemini_cmd, max_emails, read_archived_email, since, skip_fetch, expected_max_deltas, skip_task_writes, retry_deltas_file, force_refresh):
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
    
    # Merge CLI override for skip_task_writes if provided
    if skip_task_writes is not None:
        config['skip_task_writes'] = skip_task_writes
    
    prompt_path = customer_dir / PROMPT_TPL_FILENAME
    if not prompt_path.exists():
        # Fallback to global/default
        prompt_path = get_config_path(PROMPT_TPL_FILENAME)
        if not prompt_path or not prompt_path.exists():
             # Fallback to packaged default relative to this file? 
             # For now, let's assume it exists or fail
             pass 

    if not prompt_path or not prompt_path.exists():
         # Last ditch: check repo root if we are dev mode? 
         # Or just fail gracefully
         if os.environ.get('CUSTOMERS_DIR'): # Testing env often sets this
             prompt_path = Path(os.environ['CUSTOMERS_DIR']).parent / PROMPT_TPL_FILENAME
    
    if not prompt_path or not prompt_path.exists():
        click.echo(f"Error: No prompt template found. Checked {customer_dir}.", err=True)
        sys.exit(1)

    template = prompt_path.read_text()
    
    # 3. Processed Emails Tracking
    processed_emails = load_processed_emails(customer_dir)
    
    # 4. Fetch Emails
    unprocessed_emails = []
    if not skip_fetch:
        click.echo(f"DEBUG: Type of cust before fetch_and_cache_emails: {type(cust)}")
        click.echo(f"DEBUG: Content of cust before fetch_and_cache_emails: {cust}")
        click.echo(f"Fetching emails for {cust['name']}...")
        all_emails = fetch_and_cache_emails(cust, customer_dir, max_emails=max_emails, since=since, processed_ids=processed_emails)
        unprocessed_emails = filter_unprocessed_emails(all_emails, processed_emails)
    else:
        # Load from cache if skip_fetch
        email_cache = customer_dir / 'emails' / 'emails.json'
        if email_cache.exists():
            with open(email_cache) as f:
                all_emails = json.load(f)
            unprocessed_emails = filter_unprocessed_emails(all_emails, processed_emails)

    if not unprocessed_emails and not force_refresh and not retry_deltas_file:
        click.echo("No new unprocessed emails. Exiting.", err=True)
        return

    # 5. Fetch Tasks
    tasks = []
    if not skip_fetch:
        click.echo(f"DEBUG: Type of cust before fetch_and_cache_tasks: {type(cust)}")
        click.echo(f"DEBUG: Type of config before fetch_and_cache_tasks: {type(config)}")
        click.echo(f"DEBUG: Content of cust before fetch_and_cache_tasks: {cust}")
        click.echo(f"DEBUG: Content of config before fetch_and_cache_tasks: {config}")
        click.echo(f"Fetching tasks for {cust['name']}...")
        tasks_count, _ = fetch_and_cache_tasks(cust, customer_dir, project=config.get('ticktick_project', 'Work'))
        # Load the actual tasks to pass to prompt
        task_cache = customer_dir / 'tasks' / 'tasks.json'
        if task_cache.exists():
             with open(task_cache) as f: tasks = json.load(f)
    else:
         task_cache = customer_dir / 'tasks' / 'tasks.json'
         if task_cache.exists():
             with open(task_cache) as f: tasks = json.load(f)

    # 6. Prepare Prompt
    prompt_input = build_prompt(template, config, cust, unprocessed_emails, tasks, customer_dir)
    
    gemini_input_path = customer_dir / "gemini-input.txt"
    gemini_input_path.write_text(prompt_input)

    # 7. Check Existing Deltas
    deltas_path = customer_dir / "deltas.json"
    if deltas_path.exists() and not retry_deltas_file and not dry_run:
        click.echo(f"Existing deltas.json found at {deltas_path}. Please process or remove it first.", err=True)
        sys.exit(1)

    # 8. Execution / Dry Run
    if dry_run:
        click.echo(f"\nDRY_RUN=1")
        click.echo(f"Customer: {cust['name']}")
        click.echo(f"New Emails: {len(unprocessed_emails)}")
        click.echo(f"Would execute: {gemini_cmd} < {gemini_input_path}")
        click.echo(f"\n=== Prompt for Gemini MCP ===\n{prompt_input[:500]}...\n(truncated)")
        return

    # 9. Run Gemini
    if not retry_deltas_file:
        click.echo(f"Executing Gemini...")
        try:
            # Need to pass CUSTOMERS_DIR for script to find config.yaml if it relies on it
            env_vars = os.environ.copy()
            # If we are in a test env, this might be set
            
            # Construct command: pipe input file to gemini, output to deltas.json
            # We use --allowed-mcp-server-names="gemini" as a safe default we discussed
            cmd_str = f"{gemini_cmd} --allowed-mcp-server-names=\"gemini\" < {gemini_input_path} > {deltas_path}"
            
            # If gemini_cmd is an absolute path (like in tests), use it directly. 
            # If it's just 'gemini', shell=True handles path resolution.
            subprocess.run(
                cmd_str,
                shell=True,
                check=True,
                text=True,
                env=env_vars
            )
            click.echo(f"Gemini output saved to {deltas_path}")
            
        except subprocess.CalledProcessError as e:
            click.echo(f"Gemini command failed: {e}", err=True)
            sys.exit(1)

    # 10. Process Deltas
    process_deltas(deltas_path, config, customer_dir, expected_max_deltas)
    
    # 11. Update State (Mark processed)
    if not dry_run and unprocessed_emails:
        newly_processed_ids = {e['id'] for e in unprocessed_emails}
        mark_emails_processed(customer_dir, newly_processed_ids)
        click.echo(f"Marked {len(newly_processed_ids)} emails as processed.")
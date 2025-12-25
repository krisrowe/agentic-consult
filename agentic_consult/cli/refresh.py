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
from agentic_consult.utils import clean_json_output

logger = logging.getLogger(__name__)

PROMPT_TPL_FILENAME = "prompt.tpl"

def process_deltas(deltas_path: Path, config: dict, customer_dir: Path, expected_max_deltas: int = None):
    """
    Parses a deltas.json file and applies the changes (Tasks & Issues).
    Handles the new email-centric structure.
    """
    if not deltas_path.exists():
        return

    try:
        with open(deltas_path, 'r') as f:
            content = f.read()
            # Attempt to strip markdown code blocks if simple parse fails? 
            # For now, let's just log it if it fails.
            data = json.loads(content)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        if deltas_path.exists():
            click.echo(f"Debug: Raw deltas content:\n{deltas_path.read_text()}", err=True)
        click.echo(f"Warning: Could not read or parse '{deltas_path.name}'. Error: {e}", err=True)
        return

    # Flatten the new structure for processing and safety checks
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

    # --- 1. Safety Checks ---
    total_ops = len(tasks_create) + len(tasks_update)
    
    click.echo(f"\n=== Proposed Plan ({deltas_path.name}) ===")
    click.echo(json.dumps(data, indent=2))
    click.echo("========================================\n")

    if expected_max_deltas is not None and total_ops > expected_max_deltas:
        click.echo(f"SAFETY LIMIT EXCEEDED: Proposed {total_ops} changes, limit is {expected_max_deltas}.", err=True)
        sys.exit(1)

    skip_writes = config.get('skip_task_writes', False) if config else False
    project = config.get('ticktick_project', 'Work')

    # --- 2. Task Management (TickTick) ---
    
    # Create Tasks
    for task in tasks_create:
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
    for task in tasks_update:
        task_id = task.get('id')
        if not task_id: continue
        
        cmd = ['ticktick', 'tasks', 'update', task_id]
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
    
    for issue in issues_update:
        # The 'file' field in the new format corresponds to the issue filename/ID
        issue_id = issue.get('file')
        if not issue_id: continue
        
        # Sanitize filename
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

    # --- 4. Archive the Delta File ---
    if not skip_writes:
        # Move processed deltas to an archive folder to prevent re-processing
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
@click.option('--gemini-cmd', default='gemini')
@click.option('--max-emails', type=int, default=10, help="Max emails to fetch.")
@click.option('--read-archived-email/--no-read-archived-email', default=None)
@click.option('--since', help="Filter emails after date (YYYY-MM-DD).")
@click.option('--skip-fetch', is_flag=True, help="Skip fetching and use cache.")
@click.option('--expected-max-deltas', type=int, help="Fail if deltas exceed this.")
@click.option('--skip-task-writes/--no-skip-task-writes', default=None)
@click.option('--retry-deltas', 'retry_deltas_arg', type=str, is_flag=False, flag_value='deltas.json', default=None, help="Retry processing an existing deltas file.")
@click.option('--force-refresh', is_flag=True, help="Force refresh even if no new emails.") 
def refresh(identifier, dry_run, gemini_cmd, max_emails, read_archived_email, since, skip_fetch, expected_max_deltas, skip_task_writes, retry_deltas_arg, force_refresh):
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
    
    # Logic to find prompt.tpl:
    # 1. Customer specific override: customers/<slug>/prompt.tpl
    # 2. User global config override: ~/.config/agentic-consult/prompt.tpl
    # 3. Bundled default: agentic_consult/prompt.tpl (packaged with code)
    
    # 1. Customer override
    prompt_path = customer_dir / PROMPT_TPL_FILENAME
    template = None
    
    if prompt_path.exists():
        template = prompt_path.read_text()
    else:
        # 2. Global override
        global_path = get_config_path(PROMPT_TPL_FILENAME)
        if global_path and global_path.exists():
            template = global_path.read_text()
        else:
            # 3. Bundled default
            try:
                from importlib import resources
                # Python 3.9+ API
                pkg_files = resources.files('agentic_consult')
                template = (pkg_files / PROMPT_TPL_FILENAME).read_text()
            except Exception as e:
                click.echo(f"Warning: Failed to load bundled template: {e}", err=True)

    if not template:
        click.echo(f"Error: No prompt template found. Searched:\n 1. {customer_dir / PROMPT_TPL_FILENAME}\n 2. Global config\n 3. Bundled default", err=True)
        sys.exit(1)
    
    # 3. Processed Emails Tracking
    processed_emails = load_processed_emails(customer_dir)
    
    # 4. Handle --retry-deltas
    if retry_deltas_arg:
        # Determine deltas path
        retry_path = Path(retry_deltas_arg)
        if not retry_path.is_absolute():
            retry_path = customer_dir / retry_path
            
        if not retry_path.exists():
            click.echo(f"Error: Retry deltas file not found at {retry_path}", err=True)
            sys.exit(1)
            
        # Skip fetching and Gemini call
        click.echo(f"Retrying deltas from: {retry_path}")
        
        # Load deltas for acknowledgment
        try:
            with open(retry_path, 'r') as f:
                deltas = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            click.echo(f"Error: Could not read retry deltas: {e}", err=True)
            sys.exit(1)
            
        # Process deltas (this will archive it)
        process_deltas(retry_path, config, customer_dir, expected_max_deltas)
        
        # Update acknowledgment state
        if deltas:
            ack_ids = set()
            for email_entry in deltas.get('emails', []):
                if 'id' in email_entry:
                    ack_ids.add(email_entry['id'])
            
            if ack_ids:
                mark_emails_processed(customer_dir, ack_ids)
                click.echo(f"Marked {len(ack_ids)} emails as processed (from retry deltas)")
        return

    # 5. Fetch Emails
    unprocessed_emails = []
    use_mock_data = config.get('use_mock_data', False)
    if not skip_fetch:
        click.echo(f"Fetching emails for {cust['name']}...")
        fetch_and_cache_emails(cust, customer_dir, max_emails=max_emails, since=since, processed_ids=processed_emails, use_mock_data=use_mock_data)
    
    # Load from cache (whether fetched or skipped)
    email_cache = customer_dir / 'emails' / 'emails.json'
    all_emails = []
    if email_cache.exists():
        with open(email_cache) as f:
            all_emails = json.load(f)
    unprocessed_emails, _ = filter_unprocessed_emails(all_emails, processed_emails)

    if not unprocessed_emails and not force_refresh:
        click.echo("No new unprocessed emails. Exiting.", err=True)
        return

    # 6. Fetch Tasks
    tasks = []
    if not skip_fetch:
        click.echo(f"Fetching tasks for {cust['name']}...")
        fetch_and_cache_tasks(cust, customer_dir, project=config.get('ticktick_project', 'Work'), use_mock_data=use_mock_data)
        # Load the actual tasks to pass to prompt
        task_cache = customer_dir / 'tasks' / 'tasks.json'
        if task_cache.exists():
             with open(task_cache) as f: tasks = json.load(f)
    else:
         task_cache = customer_dir / 'tasks' / 'tasks.json'
         if task_cache.exists():
             with open(task_cache) as f: tasks = json.load(f)

    # 7. Prepare Prompt
    prompt_input = build_prompt(template, config, cust, unprocessed_emails, tasks, customer_dir)
    
    gemini_input_path = customer_dir / "gemini-input.txt"
    gemini_input_path.write_text(prompt_input)

    # 8. Check Existing Deltas
    deltas_path = customer_dir / "deltas.json"
    if deltas_path.exists() and not dry_run:
        # Archive existing deltas.json before creating new one
        # Use "abandoned_" prefix to distinguish from successfully processed "done_deltas_"
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        archive_name = f"abandoned_deltas_{timestamp}.json"
        archive_path = customer_dir / archive_name
        shutil.move(str(deltas_path), str(archive_path))
        click.echo(f"Archived existing deltas.json to {archive_name}")

    # 9. Execution / Dry Run
    if dry_run:
        click.echo(f"\nDRY_RUN=1")
        click.echo(f"Customer: {cust['name']}")
        click.echo(f"New Emails: {len(unprocessed_emails)}")
        click.echo(f"Would execute: {gemini_cmd} < {gemini_input_path}")
        click.echo(f"\n=== Prompt for Gemini MCP ===\n{prompt_input[:500]}...\n(truncated)")
        return

    # 10. Run Gemini
    click.echo(f"Executing Gemini...")
    try:
        env_vars = os.environ.copy()
        
        # Match successful test pattern: prompt first, then flags with empty strings
        # Use list arguments and shell=False for safety and robustness
        cmd_parts = [gemini_cmd, prompt_input]
        
        if config.get('gemini', {}).get('debug', False):
            cmd_parts.append('--debug')
            
        # Disable MCP servers and extensions using empty strings
        cmd_parts.extend(['--allowed-mcp-server-names', '', '--extensions', ''])
        
        # Capture stdout only for JSON, let stderr (logs) flow to console
        result = subprocess.run(
            cmd_parts,
            capture_output=True,
            text=True,
            env=env_vars
        )
        
        # Check return code
        result.check_returncode()
        
        # Write clean stdout to file
        with open(deltas_path, 'w') as f:
            f.write(result.stdout)
            
        click.echo(f"Gemini output saved to {deltas_path}")
        
    except subprocess.CalledProcessError as e:
        click.echo(f"Gemini command failed: {e}", err=True)
        if e.stderr:
            click.echo(f"Stderr: {e.stderr}", err=True)
        sys.exit(1)

    # 11. Load Deltas for Acknowledgment (before process_deltas archives it)
    deltas = None
    try:
        with open(deltas_path, 'r') as f:
            deltas = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        click.echo(f"Warning: Could not read deltas for acknowledgment tracking: {e}", err=True)
    
    # 12. Process Deltas (this will archive the file)
    process_deltas(deltas_path, config, customer_dir, expected_max_deltas)
    
    # 13. Update State (Mark processed based on Gemini acknowledgment)
    if deltas:
        # Collect acknowledged IDs from emails array
        ack_ids = set()
        for email_entry in deltas.get('emails', []):
            if 'id' in email_entry:
                ack_ids.add(email_entry['id'])
        
        # Mark only acknowledged emails as processed
        if ack_ids:
            mark_emails_processed(customer_dir, ack_ids)
            click.echo(f"Marked {len(ack_ids)} emails as processed (acknowledged by Gemini)")
        else:
            click.echo("Warning: No emails acknowledged in Gemini response", err=True)
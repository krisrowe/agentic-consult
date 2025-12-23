import click
import os
import sys
import yaml
import datetime
import shutil
import subprocess
from pathlib import Path

# SDK imports
from agentic_consult.customers import (
    load_customer_config, 
    _parse_customer_yaml,
    find_customer_by_id,
    get_active_customers_root
)
from agentic_consult.schema import validate_yaml
from agentic_consult.utils import is_drive_id_candidate
from agentic_consult.scanner import scan_target, get_staged_files, get_disk_files, check_git_identity
from agentic_consult.backup import perform_backup
from agentic_consult.config import (
    load_main_config, 
    save_main_config, 
    get_config_path, 
    CONFIG_FILENAME,
    load_yaml_file
)

# Defaults
PROMPT_TPL_FILENAME = "prompt.tpl"

class DriveIDParamType(click.ParamType):
    name = "drive_id"
    def convert(self, value, param, ctx):
        if is_drive_id_candidate(value):
            return value
        self.fail(f"{value} is not a valid Google Drive ID.", param, ctx)

DRIVE_ID = DriveIDParamType()

@click.group()
def main():
    """Consult CLI: Agentic Consultant Tools"""
    pass

@main.group()
def config():
    """Manage global configuration."""
    pass

@config.command(name='show')
def config_show():
    """Show current configuration."""
    data = load_main_config()
    if not data:
        click.echo("No configuration found (using defaults).")
    else:
        # Show resolved paths too for debugging
        root = get_active_customers_root()
        click.echo(f"# Active Customers Root: {root}")
        click.echo(yaml.dump(data))

@config.command(name='set')
@click.argument('key')
@click.argument('value')
def config_set(key, value):
    """Set a configuration value. 
    
    Keys:
    - customers-local-path: Path to local customers directory
    - customers-cloud-folder-id: Google Drive folder ID for backups
    """
    data = load_main_config()
    
    # Map CLI keys to config keys
    key_map = {
        'customers-local-path': 'customers_local_path',
        'customers-cloud-folder-id': 'google_drive_all_customers_folder_id'
    }
    
    real_key = key_map.get(key)
    if not real_key:
        click.echo(f"Unknown config key: {key}. Valid keys: {', '.join(key_map.keys())}", err=True)
        sys.exit(1)
        
    data[real_key] = value
    path = save_main_config(data)
    click.echo(f"Updated {key} in {path}")

@main.command()
@click.option('--output-dir', '-o', type=click.Path(path_type=Path), help="Local directory to save archives.")
@click.option('--no-upload', is_flag=True, help="Do not upload to Google Drive.")
def backup(output_dir, no_upload):
    """Backs up config and customer data."""
    config = load_main_config()
    config_path = get_config_path(CONFIG_FILENAME)
    
    if config_path and config_path.exists():
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(config_path, output_dir / CONFIG_FILENAME)
            click.echo(f"Saved config.yaml to {output_dir}")
        parent_id = config.get('google_drive_all_customers_folder_id')
        if parent_id and not no_upload:
            click.echo(f"Uploading config to {parent_id}...")
            try:
                subprocess.run(['gwsa', 'drive', 'upload', '--parent', parent_id, '--file', str(config_path)], check=True)
            except Exception as e:
                click.echo(f"Main config upload failed: {e}", err=True)

    customers_root = get_active_customers_root()
    perform_backup(config, customers_root, output_dir, no_upload)


@main.group()
def customers():
    """Manage customers."""
    pass

@customers.command(name='init')
@click.option('--slug', required=True, help="Customer slug.")
@click.option('--name', help="Customer display name.")
@click.option('--drive-id', type=DRIVE_ID, help="Existing Drive ID.")
@click.option('--drive-parent-id', type=DRIVE_ID, help="Parent Drive ID.")
@click.option('--no-prompt', is_flag=True)
def customers_init(slug, name, drive_id, drive_parent_id, no_prompt):
    """Initialize a new customer."""
    name = name or slug
    
    customers_root = get_active_customers_root()
    if not customers_root.exists():
        customers_root.mkdir(parents=True, exist_ok=True)
    
    target_dir = customers_root / slug
    if target_dir.exists():
        c_yaml = target_dir / 'customer.yaml'
        if c_yaml.exists():
            existing = _parse_customer_yaml(c_yaml)
            if existing.get('name') and existing.get('name') != name:
                click.echo(f"Conflict: Slug '{slug}' already exists with name '{existing.get('name')}'", err=True)
                sys.exit(1)

    config = load_main_config()
    parent_id = drive_parent_id or config.get('google_drive_all_customers_folder_id')
    
    if not drive_id:
        if not parent_id:
            click.echo("Error: No Drive parent ID configured or provided. Cannot discover/create folder.", err=True)
            sys.exit(1)
            
        click.echo(f"Searching for Drive folder for '{name}' in parent {parent_id}...")
        try:
            out = subprocess.check_output(['gwsa', 'drive', 'ls', parent_id], text=True, stderr=subprocess.STDOUT)
            for line in out.splitlines():
                if name.lower() in line.lower() or slug.lower() in line.lower():
                    for part in line.split():
                        if is_drive_id_candidate(part):
                            drive_id = part
                            click.echo(f"Found existing Drive folder: {drive_id}")
                            break
                if drive_id: break
        except:
            pass

    if not drive_id:
        if no_prompt:
            click.echo("Error: No Drive ID provided and none found. --no-prompt set.", err=True)
            sys.exit(1)
        if click.confirm(f"No Drive folder found for {slug}. Create one under parent {parent_id}?"):
            try:
                proc = subprocess.run(['gwsa', 'drive', 'mkdir', '--parent', parent_id, '--name', name], capture_output=True, text=True, check=True)
                drive_id = proc.stdout.strip()
                if not is_drive_id_candidate(drive_id):
                    from agentic_consult.scanner import DRIVE_ID_RE
                    m = DRIVE_ID_RE.search(proc.stdout)
                    if m: drive_id = m.group(0)
            except Exception as e:
                click.echo(f"Failed to create Drive folder: {e}", err=True)
                sys.exit(1)
        else:
            click.echo("Aborted.")
            sys.exit(1)

    target_dir.mkdir(parents=True, exist_ok=True)
    c_yaml = target_dir / 'customer.yaml'
    data = {'name': name, 'slug': slug, 'drive_folder_id': drive_id}
    with open(c_yaml, 'w') as f:
        yaml.dump(data, f)
    click.echo(f"Initialized customer '{name}' at {c_yaml}")

@customers.command(name='show')
@click.argument('identifier')
def customers_show(identifier):
    """Show configuration for a customer."""
    cust = find_customer_by_id(identifier)
    if cust:
        click.echo(yaml.dump(cust))
    else:
        click.echo(f"Customer '{identifier}' not found.", err=True)
        sys.exit(1)

@customers.command(name='refresh')
@click.argument('identifier', required=False)
@click.option('--dry-run/--no-dry-run', default=True)
@click.option('--gemini-cmd', default='gemini')
@click.option('--max-emails', default=10, help="Max emails to fetch.")
@click.option('--force-refresh', is_flag=True, help="Force re-fetching data.")
@click.option('--skip-fetch', is_flag=True, help="Skip fetching and use cache.")
def customers_refresh(identifier, dry_run, gemini_cmd, max_emails, force_refresh, skip_fetch):
    """Refreshes customer context."""
    cust = load_customer_config() if not identifier else find_customer_by_id(identifier)
    if not cust:
        click.echo("Error: Customer not found.", err=True)
        sys.exit(1)
        
    config = load_main_config()
    # Support prompt template in XDG or CWD
    tpl_path = get_config_path(PROMPT_TPL_FILENAME)
    if not tpl_path or not tpl_path.exists():
        # fallback to packaged default? or error
        click.echo("Error: prompt.tpl not found.", err=True)
        sys.exit(1)
        
    with open(tpl_path, 'r') as f: tpl = f.read()

    # Local Data Fetching
    if not skip_fetch:
        click.echo(f"Fetching data for {cust['name']}...")
        from agentic_consult.gmail import fetch_and_cache_emails
        from agentic_consult.ticktick import fetch_and_cache_tasks
        
        # Resolve customer dir
        root = get_active_customers_root()
        customer_dir = root / cust['slug']
        
        use_gemini = config.get("ticktick", {}).get("auth", {}).get("use_gemini", False)
        
        email_count = fetch_and_cache_emails(cust, customer_dir, max_emails=max_emails)
        task_count = fetch_and_cache_tasks(
            cust, 
            customer_dir, 
            project=config.get("ticktick_project", "Work"),
            use_gemini=use_gemini
        )
        
        click.echo(f"Fetched {email_count} emails and {task_count} tasks.")

    from agentic_consult.refresh import build_prompt
    prompt = build_prompt(tpl, config, cust)
    
    click.echo(f"=== Prompt for Gemini MCP (Customer: {cust['name']}) ===")
    click.echo(f"\n{prompt}\n")

    if dry_run:
        click.echo("DRY_RUN=1: Not executing. Use --no-dry-run.")
        return

    if not shutil.which(gemini_cmd):
        click.echo(f"Error: {gemini_cmd} not found.", err=True)
        sys.exit(2)

    try:
        subprocess.run([gemini_cmd, "chat", "--stdin"], input=prompt, text=True, check=True)
    except Exception as e:
        click.echo(f"Execution failed: {e}", err=True)
        sys.exit(1)

@customers.command(name='add-note')
@click.argument('identifier')
@click.option('--content', help="Markdown text content.")
@click.option('--file', 'file_path', type=click.Path(exists=True), help="Local file to import.")
@click.option('--ext', default='.md', help="File extension.")
@click.option('--name', help="Optional name.")
@click.pass_context
def customers_add_note(ctx, identifier, content, file_path, ext, name):
    """Alias for 'notes add'."""
    ctx.forward(notes_add)

@customers.group()
def notes():
    """Manage customer notes."""
    pass

@notes.command(name='add')
@click.argument('identifier')
@click.option('--content', help="Markdown text content.")
@click.option('--file', 'file_path', type=click.Path(exists=True), help="Local file to import.")
@click.option('--ext', default='.md', help="File extension for content-based notes.")
@click.option('--name', help="Optional name for the note file.")
def notes_add(identifier, content, file_path, ext, name):
    """Add a note for a customer."""
    cust = find_customer_by_id(identifier)
    if not cust:
        click.echo(f"Error: Customer '{identifier}' not found.", err=True)
        sys.exit(1)
        
    root = get_active_customers_root()
    # We assume standard structure: root / slug / notes
    notes_dir = root / cust['slug'] / 'notes'
    notes_dir.mkdir(parents=True, exist_ok=True)
    
    if file_path:
        src = Path(file_path)
        dest = notes_dir / src.name
        shutil.copy(src, dest)
        click.echo(f"Imported note to {dest}")
    elif content:
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        fname = name or f"note-{timestamp}{ext}"
        dest = notes_dir / fname
        with open(dest, 'w') as f:
            f.write(content)
        click.echo(f"Saved note to {dest}")
    else:
        click.echo("Error: Either --content or --file must be provided.", err=True)
        sys.exit(1)

@notes.command(name='list')
@click.argument('identifier')
def notes_list(identifier):
    """List notes for a customer."""
    import hashlib
    cust = find_customer_by_id(identifier)
    if not cust:
        click.echo(f"Error: Customer '{identifier}' not found.", err=True)
        sys.exit(1)
    
    root = get_active_customers_root()
    notes_dir = root / cust['slug'] / 'notes'
    
    if not notes_dir.exists():
        click.echo("No notes found.")
        return
        
    for f in notes_dir.iterdir():
        if f.is_file():
            note_id = hashlib.md5(f.name.encode()).hexdigest()[:8]
            click.echo(f"{note_id} | {f.name}")

@notes.command(name='remove')
@click.argument('identifier')
@click.argument('note_id')
def notes_remove(identifier, note_id):
    """Remove a note by its ID."""
    import hashlib
    cust = find_customer_by_id(identifier)
    if not cust:
        click.echo(f"Error: Customer '{identifier}' not found.", err=True)
        sys.exit(1)
        
    root = get_active_customers_root()
    notes_dir = root / cust['slug'] / 'notes'
    
    if not notes_dir.exists():
        click.echo("No notes found.", err=True)
        sys.exit(1)
        
    for f in notes_dir.iterdir():
        if f.is_file():
            current_id = hashlib.md5(f.name.encode()).hexdigest()[:8]
            if current_id == note_id:
                f.unlink()
                click.echo(f"Removed note: {f.name}")
                return
                
    click.echo(f"Note ID '{note_id}' not found.", err=True)
    sys.exit(1)

@notes.command(name='show')
@click.argument('identifier')
@click.argument('note_id')
def notes_show(identifier, note_id):
    """Show the content of a note by its ID."""
    import hashlib
    cust = find_customer_by_id(identifier)
    if not cust:
        click.echo(f"Error: Customer '{identifier}' not found.", err=True)
        sys.exit(1)
        
    root = get_active_customers_root()
    notes_dir = root / cust['slug'] / 'notes'
    
    if not notes_dir.exists():
        click.echo("No notes found.", err=True)
        sys.exit(1)
        
    for f in notes_dir.iterdir():
        if f.is_file():
            current_id = hashlib.md5(f.name.encode()).hexdigest()[:8]
            if current_id == note_id:
                try:
                    with open(f, 'r', encoding='utf-8') as note_file:
                        click.echo(note_file.read())
                except Exception as e:
                    click.echo(f"Error reading note: {e}", err=True)
                return
                
    click.echo(f"Note ID '{note_id}' not found.", err=True)
    sys.exit(1)

@main.command()
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

if __name__ == "__main__":
    main()

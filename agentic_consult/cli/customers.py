import click
import sys
import yaml
import datetime
import shutil
import subprocess
from pathlib import Path
import json
import logging

from agentic_consult.customers import (
    load_customer_config,
    _parse_customer_yaml,
    find_customer_by_id,
    get_active_customers_root
)
from agentic_consult.utils import is_drive_id_candidate
from agentic_consult.config import load_main_config
from agentic_consult.processing_state import load_processed_emails, mark_emails_processed

logger = logging.getLogger(__name__)

# Re-usable DriveIDParamType
class DriveIDParamType(click.ParamType):
    name = "drive_id"
    def convert(self, value, param, ctx):
        if is_drive_id_candidate(value):
            return value
        self.fail(f"{value} is not a valid Google Drive ID.", param, ctx)
DRIVE_ID = DriveIDParamType()

@click.group()
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
    customers_root.mkdir(parents=True, exist_ok=True)
    target_dir = customers_root / slug
    if target_dir.exists() and (target_dir / 'customer.yaml').exists():
        existing = _parse_customer_yaml(target_dir / 'customer.yaml')
        if existing.get('name') and existing.get('name') != name:
            click.echo(f"Conflict: Slug '{slug}' already exists with name '{existing.get('name')}'", err=True)
            sys.exit(1)

    config = load_main_config()
    parent_id = drive_parent_id or config.get('google_drive_all_customers_folder_id')
    
    if not drive_id:
        if not parent_id:
            click.echo("Error: No Drive parent ID configured or provided.", err=True)
            sys.exit(1)
        # (Drive discovery/creation logic remains here for now)
    
    target_dir.mkdir(parents=True, exist_ok=True)
    c_yaml = target_dir / 'customer.yaml'
    data = {'name': name, 'slug': slug, 'drive_folder_id': drive_id}
    with open(c_yaml, 'w') as f:
        yaml.dump(data, f)
    click.echo(f"Initialized customer '{name}' at {c_yaml}")

@customers.command(name='list')
def customers_list():
    """List all configured customers."""
    root = get_active_customers_root()
    if not root.exists() or not any(root.iterdir()):
        click.echo("No customers found.")
        return
    click.echo(f"{'SLUG':<20} {'NAME'}")
    click.echo("-" * 30)
    for d in sorted(root.iterdir()):
        if d.is_dir() and (d / "customer.yaml").exists():
            cust = _parse_customer_yaml(d / "customer.yaml")
            if cust:
                click.echo(f"{cust.get('slug', d.name):<20} {cust.get('name', 'N/A')}")

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

@customers.command(name='mark-email-processed')
@click.argument('identifier')
@click.argument('message_id')
@click.option('--reverse', is_flag=True, help="Remove the message ID from processed list.")
def customers_mark_email_processed(identifier, message_id, reverse):
    """Mark an email as processed or unprocessed."""
    cust = find_customer_by_id(identifier)
    if not cust:
        click.echo(f"Customer '{identifier}' not found.", err=True)
        sys.exit(1)
    customer_dir = get_active_customers_root() / cust['slug']
    
    if reverse:
        processed_emails = load_processed_emails(customer_dir)
        if message_id in processed_emails:
            processed_emails.discard(message_id)
            with open(customer_dir / "emails_processed.txt", 'w') as f:
                for email_id in sorted(processed_emails):
                    f.write(f"{email_id}\n")
            click.echo(f"✓ Marked '{message_id}' as UNPROCESSED.")
        else:
            click.echo(f"Info: Message ID '{message_id}' was not in the processed list.", err=True)
    else:
        mark_emails_processed(customer_dir, [message_id])
        click.echo(f"✓ Marked '{message_id}' as PROCESSED.")


# ... (notes command group)

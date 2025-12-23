"""Gmail fetching via gwsa CLI."""
import json
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List
import click


def fetch_emails(customer: Dict, max_emails: int = 10) -> List[Dict]:
    """
    Fetch unreplied emails for customer using gwsa.
    
    Args:
        customer: Customer config dict
        max_emails: Maximum number of emails to fetch
    
    Returns:
        List of email dicts
    """
    customer_name = customer.get("name")
    if not customer_name:
        return []

    if not shutil.which("gwsa"):
        click.echo("Warning: 'gwsa' CLI not found. Skipping email fetch.", err=True)
        return []

    # Search for unreplied emails from the customer
    # We use a simple search query for now
    query = f"from:{customer_name} is:unread"
    if "keywords" in customer:
        query = f"({' OR '.join(customer['keywords'])}) is:unread"

    try:
        # 1. Search for metadata first (faster)
        # Run gwsa mail search --format metadata
        search_cmd = ["gwsa", "mail", "search", query, "--max-results", str(max_emails), "--format", "metadata"]
        result = subprocess.run(search_cmd, capture_output=True, text=True, check=True)
        search_results = json.loads(result.stdout)
        
        full_emails = []
        for msg in search_results:
            msg_id = msg.get("id")
            if not msg_id: continue
            
            try:
                # 2. Fetch full content for each message
                read_cmd = ["gwsa", "mail", "read", msg_id]
                read_result = subprocess.run(read_cmd, capture_output=True, text=True, check=True)
                full_email = json.loads(read_result.stdout)
                full_emails.append(full_email)
            except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
                click.echo(f"Warning: Failed to read email {msg_id}: {e}", err=True)
                continue
                
        return full_emails
    except subprocess.CalledProcessError as e:

        click.echo(f"Error calling gwsa: {e.stderr}", err=True)
        return []
    except json.JSONDecodeError:
        click.echo("Error decoding gwsa output", err=True)
        return []


def save_emails_to_json(emails: List[Dict], emails_dir: Path) -> None:
    """
    Save emails to JSON files.
    
    Args:
        emails: List of email dicts
        emails_dir: Directory to save email JSONs
    """
    emails_dir.mkdir(parents=True, exist_ok=True)
    
    # Save all emails in a single file for the prompt to reference
    emails_file = emails_dir / 'emails.json'
    with open(emails_file, 'w') as f:
        json.dump(emails, f, indent=2)


def fetch_and_cache_emails(customer: Dict, customer_dir: Path, max_emails: int = 10) -> int:
    """
    Fetch emails and cache them locally.
    
    Args:
        customer: Customer config dict
        customer_dir: Customer's data directory
        max_emails: Maximum number of emails to fetch
    
    Returns:
        Number of emails fetched
    """
    emails_dir = customer_dir / 'emails'
    
    # Fetch emails
    emails = fetch_emails(customer, max_emails=max_emails)
    
    # Save emails
    if emails:
        save_emails_to_json(emails, emails_dir)
    
    return len(emails)

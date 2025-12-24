"""Gmail fetching via gwsa CLI."""
import json
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List
import click


def fetch_emails(customer: Dict, customer_dir: Path, manifest: Dict, max_emails: int = 50, include_archived: bool = False, since: str = None) -> List[Dict]:
    """
    Fetch unreplied emails for a customer, using a manifest to skip downloads and use a local cache.
    Returns a single list of source-aware email objects.
    """
    if not shutil.which("gwsa"):
        click.echo("Warning: 'gwsa' CLI not found. Skipping email fetch.", err=True)
        return []

    individual_emails_dir = customer_dir / 'emails' / 'individual'
    individual_emails_dir.mkdir(parents=True, exist_ok=True)

    processed_ids = manifest.get('processed_ids', set())
    local_unprocessed_ids = manifest.get('local_unprocessed_ids', set())

    # Build Gmail query
    base_query = f"from:{customer.get('name')}"
    if "keywords" in customer:
        base_query = f"({' OR '.join(customer['keywords'])})"
    query_parts = [base_query]
    if not include_archived:
        query_parts.append("is:unread")
    if since:
        query_parts.append(f"after:{since}")
    query = " ".join(query_parts)
    click.echo(f"1. Searching for emails with query: '{query}' (limit: {max_emails})", err=True)

    try:
        # 1. Get remote IDs
        search_cmd = ["gwsa", "mail", "search", query, "--max-results", str(max_emails), "--format", "metadata"]
        result = subprocess.run(search_cmd, capture_output=True, text=True, check=True)
        search_results = json.loads(result.stdout)
        remote_ids = {msg.get("id") for msg in search_results if msg.get("id")}
        
        # 2. Calculate what to fetch vs. load from cache
        new_ids_to_download = remote_ids - processed_ids - local_unprocessed_ids
        
        click.echo(f"   Found {len(remote_ids)} matching email(s): {len(new_ids_to_download)} new, {len(local_unprocessed_ids)} in cache.", err=True)

        source_aware_emails = []
        all_ids_to_process = local_unprocessed_ids.union(new_ids_to_download)
        total_to_process = len(all_ids_to_process)

        if not total_to_process:
            click.echo("   No new or unprocessed emails to retrieve.", err=True)
            return []

        click.echo("2. Retrieving email content...", err=True)
        
        for i, msg_id in enumerate(all_ids_to_process):
            cached_email_path = individual_emails_dir / f"{msg_id}.json"
            
            if cached_email_path.exists():
                action = "Loading from cache"
                progress_text = f"--> {action}: {i+1}/{total_to_process}"
                click.echo(f"\r{progress_text:<50}", nl=False, err=True)
                try:
                    with open(cached_email_path, 'r') as f:
                        email_data = json.load(f)
                        email_data['_source'] = 'cache'
                        source_aware_emails.append(email_data)
                    continue
                except (json.JSONDecodeError, IOError) as e:
                    click.echo(f"\nWarning: Failed to read cached email {msg_id}, will re-download. Error: {e}", err=True)

            action = "Downloading"
            progress_text = f"--> {action}: {i+1}/{total_to_process}"
            click.echo(f"\r{progress_text:<50}", nl=False, err=True)
            
            try:
                read_cmd = ["gwsa", "mail", "read", msg_id]
                read_result = subprocess.run(read_cmd, capture_output=True, text=True, check=True)
                full_email = json.loads(read_result.stdout)
                
                with open(cached_email_path, 'w') as f:
                    json.dump(full_email, f, indent=2)
                
                full_email['_source'] = 'remote'
                source_aware_emails.append(full_email)
            except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
                click.echo(f"\nWarning: Failed to read/cache email {msg_id}: {e}", err=True)

        click.echo("\r" + " " * 60, nl=False, err=True)
        click.echo(f"\r   ✓ Retrieval complete.", err=True)
        
        return source_aware_emails

    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        click.echo(f"Error calling gwsa: {getattr(e, 'stderr', e)}", err=True)
        return []

def save_emails_to_json(emails: List[Dict], emails_dir: Path) -> None:
    """Saves a combined list of emails to the main emails.json file."""
    emails_dir.mkdir(parents=True, exist_ok=True)
    emails_file = emails_dir / 'emails.json'
    with open(emails_file, 'w') as f:
        json.dump(emails, f, indent=2)

def fetch_and_cache_emails(customer: Dict, customer_dir: Path, processed_ids: set, max_emails: int = 50, include_archived: bool = False, since: str = None, use_mock_data: bool = False) -> (int, Dict):
    """
    Builds a manifest of local/processed emails, fetches new ones, and returns stats.
    """
    emails_dir = customer_dir / 'emails'
    stats = {"remote": 0, "cache": 0}
    
    if use_mock_data:
        mock_file = customer_dir / 'mock-emails.json'
        if mock_file.exists():
            click.echo(f"Using mock emails from {mock_file}", err=True)
            try:
                with open(mock_file, 'r') as f:
                    emails = json.load(f)
                save_emails_to_json(emails, emails_dir)
                stats['remote'] = len(emails)
                return len(emails), stats
            except Exception as e:
                click.echo(f"Error reading mock emails: {e}", err=True)
                return 0, stats
        else:
             click.echo(f"Warning: use_mock_data is true but {mock_file} not found.", err=True)
             return 0, stats

    # 1. Build Manifest
    individual_emails_dir = emails_dir / 'individual'
    individual_emails_dir.mkdir(parents=True, exist_ok=True)
    
    all_local_ids = {f.stem for f in individual_emails_dir.glob("*.json")}
    local_unprocessed_ids = all_local_ids - processed_ids
    
    manifest = {
        "processed_ids": processed_ids,
        "local_unprocessed_ids": local_unprocessed_ids
    }
    
    # 2. Fetch emails
    source_aware_emails = fetch_emails(
        customer, customer_dir, manifest, max_emails, include_archived, since
    )
    
    # 3. Calculate stats from the source-aware list
    for email in source_aware_emails:
        source = email.get('_source', 'remote') # Default to remote if key is missing
        if source in stats:
            stats[source] += 1
            
    # 4. Create a clean list for saving and downstream processing
    clean_emails = [{k: v for k, v in email.items() if k != '_source'} for email in source_aware_emails]
    
    if not clean_emails:
        return 0, stats
    
    # 5. Save the combined list to the main emails.json for the prompt
    if clean_emails:
        save_emails_to_json(clean_emails, emails_dir)
    
    return len(clean_emails), stats

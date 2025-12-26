"""Gmail fetching via gwsa CLI."""
import json
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List
import click


def fetch_emails(customer: Dict, customer_dir: Path, candidates: List[Dict], total_to_load: int) -> List[Dict]:
    """
    Loads email content for candidates from disk or Gmail API.
    """
    if not candidates:
        return []

    individual_emails_dir = customer_dir / 'emails' / 'individual'
    individual_emails_dir.mkdir(parents=True, exist_ok=True)

    source_aware_emails = []
    
    click.echo(f"Phase 2: Loading email content for {total_to_load} emails...", err=True)
    
    loaded_count = 0
    for entry in candidates:
        msg_id = entry['message_id']
        cached_email_path = individual_emails_dir / f"{msg_id}.json"
        email_data = None

        if entry['available_on_disk']:
            try:
                with open(cached_email_path, 'r') as f:
                    email_data = json.load(f)
                    email_data['_source'] = 'cache'
            except (json.JSONDecodeError, IOError) as e:
                click.echo(f"\nWarning: Failed to read cached email {msg_id}. Error: {e}", err=True)
                # Fall back to cloud if possible
                if not entry['available_in_cloud']:
                    continue

        if not email_data and entry['available_in_cloud']:
            if not shutil.which("gwsa"):
                continue
            try:
                read_cmd = ["gwsa", "mail", "read", msg_id]
                read_result = subprocess.run(read_cmd, capture_output=True, text=True, check=True)
                email_data = json.loads(read_result.stdout)
                
                with open(cached_email_path, 'w') as f:
                    json.dump(email_data, f, indent=2)
                
                email_data['_source'] = 'remote'
            except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
                click.echo(f"\nWarning: Failed to read/cache email {msg_id}: {e}", err=True)
                continue

        if email_data:
            source_aware_emails.append(email_data)
            loaded_count += 1
            progress = (loaded_count / total_to_load) * 100
            click.echo(f"\r   Loading emails: {loaded_count}/{total_to_load} ({progress:.0f}%)", nl=False, err=True)

    click.echo("\r" + " " * 60, nl=False, err=True)
    click.echo(f"\r   ✓ Loading complete.", err=True)
    
    return source_aware_emails

def save_emails_to_json(emails: List[Dict], emails_dir: Path) -> None:
    """Saves a combined list of emails to the main emails.json file."""
    emails_dir.mkdir(parents=True, exist_ok=True)
    emails_file = emails_dir / 'emails.json'
    with open(emails_file, 'w') as f:
        json.dump(emails, f, indent=2)

def fetch_and_cache_emails(customer: Dict, customer_dir: Path, processed_ids: set, max_emails: int = 50, include_archived: bool = False, since: str = None, use_mock_data: bool = False) -> (int, Dict):
    """
    Builds a candidate list from cloud and disk, reports stats, and loads unprocessed emails.
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

    # Phase 1: Build Candidate List
    click.echo("Phase 1: Building candidate list...", err=True)
    
    # 1. Get cloud IDs
    cloud_ids = set()
    if shutil.which("gwsa"):
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
        
        click.echo(f"   Querying Gmail: '{query}'", err=True)
        try:
            search_cmd = ["gwsa", "mail", "search", query, "--max-results", str(max_emails), "--format", "metadata"]
            result = subprocess.run(search_cmd, capture_output=True, text=True, check=True)
            search_results = json.loads(result.stdout)
            cloud_ids = {msg.get("id") for msg in search_results if msg.get("id")}
        except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
            click.echo(f"   Warning: Gmail search failed: {e}", err=True)

    # 2. Get local IDs
    individual_emails_dir = emails_dir / 'individual'
    individual_emails_dir.mkdir(parents=True, exist_ok=True)
    local_ids = {f.stem for f in individual_emails_dir.glob("*.json")}
    
    # 3. Build Master List
    master_candidates = {}
    for mid in cloud_ids | local_ids:
        master_candidates[mid] = {
            'message_id': mid,
            'available_in_cloud': mid in cloud_ids,
            'available_on_disk': mid in local_ids,
            'is_processed': mid in processed_ids
        }
    
    # 4. Generate Stats
    total_candidates = len(master_candidates)
    cloud_only = sum(1 for c in master_candidates.values() if c['available_in_cloud'] and not c['available_on_disk'])
    disk_only = sum(1 for c in master_candidates.values() if not c['available_in_cloud'] and c['available_on_disk'])
    both = sum(1 for c in master_candidates.values() if c['available_in_cloud'] and c['available_on_disk'])
    already_processed = sum(1 for c in master_candidates.values() if c['is_processed'])
    to_process = total_candidates - already_processed
    
    click.echo(f"   Total candidates: {total_candidates}", err=True)
    click.echo(f"   - From cloud only: {cloud_only}", err=True)
    click.echo(f"   - From disk only: {disk_only}", err=True)
    click.echo(f"   - Available in both: {both}", err=True)
    click.echo(f"   - Already processed: {already_processed}", err=True)
    click.echo(f"   - To process: {to_process}", err=True)
    
    if to_process == 0:
        return 0, stats

    # 5. Filter unprocessed candidates
    unprocessed_candidates = [c for c in master_candidates.values() if not c['is_processed']]
    
    # Phase 2: Filter and Load
    source_aware_emails = fetch_emails(customer, customer_dir, unprocessed_candidates, to_process)
    
    # 6. Calculate stats
    for email in source_aware_emails:
        source = email.get('_source', 'remote')
        if source in stats:
            stats[source] += 1
            
    # 7. Create a clean list for saving
    clean_emails = [{k: v for k, v in email.items() if k != '_source'} for email in source_aware_emails]
    
    if clean_emails:
        save_emails_to_json(clean_emails, emails_dir)
    
    return len(clean_emails), stats

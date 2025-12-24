"""Email processing state management."""
from pathlib import Path
from typing import Set
import logging

logger = logging.getLogger(__name__)

PROCESSED_EMAILS_FILENAME = "emails_processed.txt"


def load_processed_emails(customer_dir: Path) -> Set[str]:
    """Load the set of processed email IDs from emails_processed.txt in customer directory."""
    processed_file = customer_dir / PROCESSED_EMAILS_FILENAME
    
    if not processed_file.exists():
        logger.debug(f"No processed emails file found at {processed_file}")
        return set()
    
    try:
        with open(processed_file, 'r') as f:
            email_ids = {line.strip() for line in f if line.strip()}
        logger.debug(f"Loaded {len(email_ids)} processed email IDs from {processed_file}")
        return email_ids
    except Exception as e:
        logger.error(f"Error loading processed emails from {processed_file}: {e}")
        return set()


def mark_emails_processed(customer_dir: Path, email_ids: list[str]) -> None:
    """Mark emails as processed by appending their IDs to emails_processed.txt in customer directory."""
    if not email_ids:
        return
    
    processed_file = customer_dir / PROCESSED_EMAILS_FILENAME
    
    try:
        customer_dir.mkdir(parents=True, exist_ok=True)
        
        with open(processed_file, 'a') as f:
            for email_id in email_ids:
                f.write(f"{email_id}\n")
        
        logger.info(f"Marked {len(email_ids)} emails as processed")
    except Exception as e:
        logger.error(f"Error marking emails as processed: {e}")


def filter_unprocessed_emails(emails: list[dict], processed_emails: Set[str]) -> tuple[list[dict], int]:
    """Filter out emails that have already been processed."""
    unprocessed = []
    skipped_count = 0
    
    for email in emails:
        email_id = email.get('id')
        if not email_id:
            logger.warning(f"Email missing 'id' field: {email.get('subject', 'Unknown')}")
            continue
        
        if email_id in processed_emails:
            logger.debug(f"Skipping email {email_id}: already processed")
            skipped_count += 1
        else:
            unprocessed.append(email)
    
    return unprocessed, skipped_count

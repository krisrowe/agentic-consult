"""Gmail label operations using google-auth credentials.

All operations are idempotent - adding a label that exists or removing
one that's already removed will not raise errors.

Supports both single message IDs and batches for efficiency.
"""

import logging
from typing import Union

import google.auth
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

GMAIL_SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

# System labels use their name as ID
SYSTEM_LABELS = {
    'INBOX', 'UNREAD', 'STARRED', 'IMPORTANT', 'SENT', 'DRAFT',
    'SPAM', 'TRASH', 'CHAT', 'CATEGORY_PERSONAL', 'CATEGORY_SOCIAL',
    'CATEGORY_PROMOTIONS', 'CATEGORY_UPDATES', 'CATEGORY_FORUMS'
}

# Cache label name -> ID mappings per session
_label_id_cache: dict[str, str] = {}
_service_cache = None


def _get_service():
    """Get or create Gmail API service using default credentials."""
    global _service_cache
    if _service_cache is None:
        creds, _ = google.auth.default(scopes=GMAIL_SCOPES)
        _service_cache = build('gmail', 'v1', credentials=creds)
    return _service_cache


def _normalize_ids(message_ids: Union[str, list[str]]) -> list[str]:
    """Normalize single ID or list to list."""
    if isinstance(message_ids, str):
        return [message_ids]
    return list(message_ids)


def _get_label_id(label_name: str) -> str:
    """Get label ID for a label name, creating if needed for user labels."""
    if label_name in SYSTEM_LABELS:
        return label_name

    if label_name in _label_id_cache:
        return _label_id_cache[label_name]

    service = _get_service()

    # List all labels to find existing
    results = service.users().labels().list(userId='me').execute()
    for label in results.get('labels', []):
        _label_id_cache[label['name']] = label['id']
        if label['name'] == label_name:
            return label['id']

    # Not found - create it
    logger.info(f"Creating label: {label_name}")
    new_label = service.users().labels().create(
        userId='me',
        body={'name': label_name, 'labelListVisibility': 'labelShow', 'messageListVisibility': 'show'}
    ).execute()
    _label_id_cache[label_name] = new_label['id']
    return new_label['id']


def add_label(message_ids: Union[str, list[str]], label_name: str) -> dict:
    """Add a label to one or more messages.

    Idempotent - no error if label already applied.
    Uses batch API for multiple messages.

    Args:
        message_ids: Single message ID or list of IDs
        label_name: Label name (e.g., 'Reviewing', 'STARRED')

    Returns:
        dict with success status and count
    """
    ids = _normalize_ids(message_ids)
    if not ids:
        return {'success': True, 'modified': 0}

    service = _get_service()
    label_id = _get_label_id(label_name)

    try:
        if len(ids) == 1:
            service.users().messages().modify(
                userId='me',
                id=ids[0],
                body={'addLabelIds': [label_id]}
            ).execute()
        else:
            service.users().messages().batchModify(
                userId='me',
                body={'ids': ids, 'addLabelIds': [label_id]}
            ).execute()

        return {'success': True, 'modified': len(ids), 'label': label_name}

    except HttpError as e:
        logger.error(f"Failed to add label {label_name}: {e}")
        return {'success': False, 'error': str(e), 'label': label_name}


def remove_label(message_ids: Union[str, list[str]], label_name: str) -> dict:
    """Remove a label from one or more messages.

    Idempotent - no error if label not present.
    Uses batch API for multiple messages.

    Args:
        message_ids: Single message ID or list of IDs
        label_name: Label name (e.g., 'INBOX', 'Reviewing')

    Returns:
        dict with success status and count
    """
    ids = _normalize_ids(message_ids)
    if not ids:
        return {'success': True, 'modified': 0}

    service = _get_service()

    # For removal, if label doesn't exist, nothing to remove
    if label_name in SYSTEM_LABELS:
        label_id = label_name
    elif label_name in _label_id_cache:
        label_id = _label_id_cache[label_name]
    else:
        # Check if it exists
        results = service.users().labels().list(userId='me').execute()
        label_id = None
        for label in results.get('labels', []):
            _label_id_cache[label['name']] = label['id']
            if label['name'] == label_name:
                label_id = label['id']
                break

        if label_id is None:
            # Label doesn't exist, nothing to remove - idempotent success
            return {'success': True, 'modified': 0, 'label': label_name, 'note': 'label does not exist'}

    try:
        if len(ids) == 1:
            service.users().messages().modify(
                userId='me',
                id=ids[0],
                body={'removeLabelIds': [label_id]}
            ).execute()
        else:
            service.users().messages().batchModify(
                userId='me',
                body={'ids': ids, 'removeLabelIds': [label_id]}
            ).execute()

        return {'success': True, 'modified': len(ids), 'label': label_name}

    except HttpError as e:
        logger.error(f"Failed to remove label {label_name}: {e}")
        return {'success': False, 'error': str(e), 'label': label_name}


def archive(message_ids: Union[str, list[str]]) -> dict:
    """Archive messages by removing INBOX label.

    Convenience wrapper around remove_label.

    Args:
        message_ids: Single message ID or list of IDs

    Returns:
        dict with success status and count
    """
    return remove_label(message_ids, 'INBOX')


def list_inbox(
    review_status: str = "all",
    review_label: str = "Reviewing",
    limit: int = 100
) -> dict:
    """List message IDs currently in inbox.

    Queries Gmail directly - source of truth for triage state.

    Args:
        review_status: Filter by review state:
            - "all": All inbox messages
            - "new": Inbox messages WITHOUT review label
            - "reviewing": Inbox messages WITH review label
        review_label: Name of the review label (default: "Reviewing")
        limit: Max messages to return (default: 100)

    Returns:
        dict with message_ids, count, query, elapsed_ms
    """
    import time

    service = _get_service()

    if review_status == "new":
        query = f"in:inbox -label:{review_label}"
    elif review_status == "reviewing":
        query = f"in:inbox label:{review_label}"
    else:
        query = "in:inbox"

    start = time.time()

    try:
        message_ids = []
        page_token = None

        while len(message_ids) < limit:
            results = service.users().messages().list(
                userId='me',
                q=query,
                maxResults=min(limit - len(message_ids), 100),
                pageToken=page_token
            ).execute()

            messages = results.get('messages', [])
            message_ids.extend(m['id'] for m in messages)

            page_token = results.get('nextPageToken')
            if not page_token:
                break

        elapsed_ms = int((time.time() - start) * 1000)

        return {
            'message_ids': message_ids[:limit],
            'count': len(message_ids[:limit]),
            'query': query,
            'elapsed_ms': elapsed_ms
        }

    except HttpError as e:
        logger.error(f"Failed to list inbox: {e}")
        return {'message_ids': [], 'count': 0, 'error': str(e)}

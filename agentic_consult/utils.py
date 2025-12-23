import re

DATE_PREFIX_RE = re.compile(r'^\d{2}-\d{2}-\d{2}_')

def is_drive_id_candidate(token):
    """
    Heuristic: A Drive ID should be 20-70 chars, mixed case/digits.
    Must NOT look like a date-prefixed filename (YY-MM-DD_...).
    """
    if not token or not (20 <= len(token) <= 70):
        return False
    # Must contain at least one digit and one letter
    if not re.search(r'\d', token) or not re.search(r'[A-Za-z]', token):
        return False
    # Explicitly ignore tokens starting with date pattern (issue filenames)
    if DATE_PREFIX_RE.match(token):
        return False
    return True

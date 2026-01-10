import os
import re
import subprocess
import logging
from pathlib import Path
from agentic_consult.utils import is_drive_id_candidate

logger = logging.getLogger(__name__)

# Regex definitions
EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
DRIVE_ID_RE = re.compile(r'[A-Za-z0-9_-]{20,70}')
TICKET_ID_RE = re.compile(r'\bb/\d{6,}\b')
DRIVE_KEY_RE = re.compile(r'(drive_folder_id|drive-folder-id|drivefolderid)[:=\s]+[\"\']?(?P<id>[A-Za-z0-9_-]+)[\"\']?', re.IGNORECASE)
DRIVE_URL_RE = re.compile(r'/d/(?P<id>[A-Za-z0-9_-]{20,70})')
QUERY_ID_RE = re.compile(r'id=(?P<id>[A-Za-z0-9_-]{20,70})')
PARENT_ID_RE = re.compile(r'parent[-_ ]folder[-_ ]id[:=\s]+(?P<id>[A-Za-z0-9_-]{20,70})', re.IGNORECASE)

def get_staged_files():
    """Returns a list of paths for files that are currently staged."""
    try:
        cmd = ['git', 'diff', '--cached', '--name-only', '-z', '--diff-filter=ACMRT']
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        files = result.stdout.strip('\0').split('\0')
        return [f for f in files if f]
    except subprocess.CalledProcessError:
        return []

def get_disk_files(path=".", include_ignored=False):
    """
    Returns a list of all files in the given path.
    If include_ignored is False, tries to respect gitignore.
    """
    path = Path(path)
    if not include_ignored:
        try:
            # git ls-files to respect ignore rules
            cmd = ['git', 'ls-files', '--cached', '--others', '--exclude-standard']
            result = subprocess.run(cmd, cwd=path, capture_output=True, text=True, check=True)
            return [str(path / f) for f in result.stdout.splitlines()]
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.debug(f"git ls-files failed or not found, falling back to os.walk: {e}")
            
    all_files = []
    for root, dirs, files in os.walk(path):
        if ".git" in dirs:
            dirs.remove(".git")
        for f in files:
            all_files.append(str(Path(root) / f))
    return all_files


def read_file_content(path, staged=False):
    """
    Reads content from disk or from git index (staged).
    """
    if staged:
        # Read from git index
        # path needs to be relative to repo root for git show
        # Assuming CWD is repo root for now, or we'd need git root detection
        try:
            cmd = ['git', 'show', f':{path}']
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout
        except subprocess.CalledProcessError:
            return "" # File might be deleted or not in index
    else:
        # Read from disk
        if not os.path.exists(path):
            return ""
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
        except OSError:
            return ""

def scan_text(text, patterns, line_offset=0, allowed_emails=None):
    """Scans a block of text for patterns. Returns list of dicts."""
    findings = []
    allowed_emails = set(allowed_emails or [])
    
    for i, line in enumerate(text.splitlines(), start=1 + line_offset):
        line = line.strip()
        if not line: continue
        
        for p_val, p_meta in patterns.items():
            if p_val.lower() in line.lower():
                 findings.append({
                     'type': 'keyword',
                     'subtype': p_meta['type'],
                     'customer': p_meta.get('customer'),
                     'value': p_val,
                     'line': i,
                     'msg': f"Found {p_meta['type']} '{p_val}' ({p_meta.get('customer', 'unknown')})"
                 })
                 
        email_match = EMAIL_RE.search(line)
        if email_match:
            email = email_match.group(0)
            if email not in allowed_emails:
                findings.append({
                    'type': 'email',
                    'value': email,
                    'line': i,
                    'msg': f"Found email '{email}'"
                })
            else:
                logger.debug(f"Ignoring allowed email '{email}' at Line {i}")
                
        if TICKET_ID_RE.search(line):
            findings.append({
                'type': 'ticket_id',
                'line': i,
                'msg': "Found ticket ID"
            })
            
        for regex in [DRIVE_KEY_RE, DRIVE_URL_RE, QUERY_ID_RE, PARENT_ID_RE]:
            m = regex.search(line)
            if m:
                val = m.group('id')
                if is_drive_id_candidate(val):
                    findings.append({
                        'type': 'drive_id',
                        'value': val,
                        'line': i,
                        'msg': f"Found Drive ID '{val}' in context"
                    })
    return findings

def scan_target(path, patterns, staged=False, allowed_emails=None):
    """
    Scans a single target (file path).
    Checks filename and content. Returns list of dicts.
    """
    findings = []
    fname = Path(path).name
    
    # 1. Check Filename
    for p_val, p_meta in patterns.items():
        if p_val.lower() in fname.lower():
             findings.append({
                 'type': 'filename',
                 'subtype': p_meta['type'],
                 'customer': p_meta.get('customer'),
                 'value': p_val,
                 'msg': f"Filename contains sensitive term '{p_val}' ({p_meta['type']})"
             })

    # 2. Check Content
    content = read_file_content(path, staged=staged)
    if content:
        # Pass filename context? No, just return list
        res = scan_text(content, patterns, allowed_emails=allowed_emails)
        findings.extend(res)
        
    return findings


def check_git_identity(path="."):
    """
    Ensures that for every repository, the committer identity is either 
    perfectly consistent with the entire history or explicitly declared 
    via a local configuration.
    """
    from agentic_consult.config import load_main_config
    path = Path(path)
    try:
        # 1. Data Retrieval: Impending Email
        res = subprocess.run(['git', 'var', 'GIT_AUTHOR_IDENT'], cwd=path, capture_output=True, text=True)
        if res.returncode != 0:
            return [] # Not a git repo or can't determine ident
        
        match = re.search(r'<(.*)>', res.stdout)
        if not match:
             return []
        impending_email = match.group(1).strip()

        # 1. Data Retrieval: Local Email
        local_check = subprocess.run(
            ['git', 'config', '--local', '--get', 'user.email'], 
            cwd=path, capture_output=True, text=True
        )
        has_local_config = (local_check.returncode == 0)
        local_email = local_check.stdout.strip() if has_local_config else None

        # 2. Execution Flow: Local Configuration is Present
        if has_local_config:
            # Requirement: All unpushed commits must match Local Email
            try:
                # Get unpushed commits: HEAD but not upstream
                res = subprocess.run(['git', 'log', '@{u}..HEAD', '--format=%ae'], cwd=path, capture_output=True, text=True)
                if res.returncode == 0:
                    unpushed_emails = set(e.strip() for e in res.stdout.splitlines() if e.strip())
                    mismatches = unpushed_emails - {local_email}
                    if mismatches:
                        return [f"Identity Mismatch! Unpushed work is inconsistent with configured local identity '{local_email}': {mismatches}"]
            except subprocess.CalledProcessError:
                pass # Likely no upstream, skip unpushed check
            
            # If everything matches or check skipped
            return []

        # 2. Execution Flow: Local Configuration is Missing
        # Requirement: Every commit in entire history must match Impending Email
        res = subprocess.run(['git', 'log', '--format=%ae'], cwd=path, capture_output=True, text=True)
        if res.returncode == 0:
            history_emails = set(e.strip() for e in res.stdout.splitlines() if e.strip())
            
            # Pass if pristine (empty or all same as impending)
            if not history_emails or history_emails == {impending_email}:
                return []
            
            # Conflict detected. Check Safety Valve (Override).
            settings = load_main_config()
            is_optional = settings.get('precommit', {}).get('git_local_user_identity_optional', False)
            
            if is_optional:
                return [] # Bypass enforcement
                
            # Fail with guidance
            return [
                f"Identity Mismatch! Repo history is inconsistent with impending identity '{impending_email}': {history_emails}.",
                f"To resolve this, choose one:",
                f"  1. Set Local Identity:   git config user.email {impending_email}",
                f"  2. Disable Enforcement:  consult config set precommit.git_local_user_identity_optional true"
            ]
            
        return []

    except Exception as e:
        logger.debug(f"Identity check failed: {e}")
        return []


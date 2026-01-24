#!/usr/bin/env python3
"""
Migrate email archive filenames to use UTC timestamps.

Historical emails were stored with sender's timezone in the filename.
This script normalizes all filenames to UTC based on the Date header
stored inside each .meta file.

Usage:
    # Dry run
    python scripts/standardize-email-file-names.py --dry-run gs://bucket/email-archive

    # Apply with default batch size (50)
    python scripts/standardize-email-file-names.py gs://bucket/email-archive

    # Custom batch size
    python scripts/standardize-email-file-names.py --batch-size 100 gs://bucket/email-archive

The script is idempotent - running it multiple times is safe.
"""

import argparse
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from email.parser import HeaderParser
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional


def get_default_path() -> str:
    if env_path := os.environ.get("EMAIL_ARCHIVE_DATA_DIR"):
        return env_path
    xdg_data = os.environ.get("XDG_DATA_HOME")
    return str((Path(xdg_data) if xdg_data else Path.home() / ".local" / "share") / "email-archive")


def is_gcs_path(path: str) -> bool:
    return path.startswith("gs://")


def parse_date_from_content(content: str) -> Optional[datetime]:
    msg = HeaderParser().parsestr(content)
    date_str = msg.get("Date")
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    except Exception:
        pass
    return None


def compute_utc_prefix(dt: datetime) -> str:
    if dt.tzinfo is not None:
        dt_utc = dt.astimezone(timezone.utc)
    else:
        dt_utc = dt.replace(tzinfo=timezone.utc)
    return dt_utc.strftime("%Y%m%d-%H%M%S")


def run_gcs_batched(data_path: str, batch_size: int, dry_run: bool):
    """Process GCS files in batches for speed."""

    # 1. List ALL files once
    print(f"Listing files...", file=sys.stderr, flush=True)
    result = subprocess.run(
        ["gsutil", "ls", f"{data_path}/*"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"ERROR: gsutil ls failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    all_files = [line.split("/")[-1] for line in result.stdout.strip().split("\n") if line]
    meta_files = [f for f in all_files if f.endswith(".meta")]

    # Build lookup of all files by base name (prefix_msgid)
    files_by_base = {}
    for f in all_files:
        base = f.rsplit(".", 1)[0]  # strip extension
        files_by_base.setdefault(base, []).append(f)

    print(f"Found {len(meta_files)} emails, {len(all_files)} total files", file=sys.stderr)

    total = len(meta_files)
    width = len(str(total))
    stats = {"renamed": 0, "skipped": 0, "error": 0}
    all_renames = []  # collect all renames

    # 2. Process in batches
    num_batches = (len(meta_files) + batch_size - 1) // batch_size
    for batch_start in range(0, len(meta_files), batch_size):
        batch_end = min(batch_start + batch_size, len(meta_files))
        batch = meta_files[batch_start:batch_end]
        batch_num = batch_start // batch_size + 1
        batch_pct = (batch_end * 100) // total

        print(f"Batch {batch_num}/{num_batches} ({batch_pct}%): downloading {len(batch)} .meta files...", file=sys.stderr, flush=True)

        # Download batch to temp dir
        with tempfile.TemporaryDirectory() as tmpdir:
            # Build list of files to download
            src_files = [f"{data_path}/{f}" for f in batch]

            # gsutil -m cp for parallel download
            proc = subprocess.run(
                ["gsutil", "-m", "cp"] + src_files + [tmpdir + "/"],
                capture_output=True, text=True
            )
            if proc.returncode != 0:
                print(f"WARNING: batch download had errors: {proc.stderr}", file=sys.stderr)

            # Process each file in batch
            for i, meta_file in enumerate(batch):
                idx = batch_start + i + 1
                prog = f"[{idx:0{width}d}/{total:0{width}d} ({(idx*100)//total}%)]"

                local_path = Path(tmpdir) / meta_file
                if not local_path.exists():
                    print(f"ERROR: {meta_file} - download failed {prog}", file=sys.stderr)
                    stats["error"] += 1
                    continue

                content = local_path.read_text(encoding="utf-8")
                email_dt = parse_date_from_content(content)

                if not email_dt:
                    print(f"ERROR: {meta_file} - no date {prog}", file=sys.stderr)
                    stats["error"] += 1
                    continue

                # Parse current prefix and message_id
                stem = meta_file.rsplit(".", 1)[0]
                parts = stem.split("_", 1)
                if len(parts) != 2:
                    print(f"ERROR: {meta_file} - bad format {prog}", file=sys.stderr)
                    stats["error"] += 1
                    continue

                current_prefix, msg_id = parts
                utc_prefix = compute_utc_prefix(email_dt)
                base = f"{current_prefix}_{msg_id}"

                if current_prefix == utc_prefix:
                    print(f"{meta_file} (no change) {prog}", file=sys.stderr)
                    stats["skipped"] += 1
                    continue

                # Find all related files
                related = files_by_base.get(base, [])
                for old_name in related:
                    new_name = old_name.replace(f"{current_prefix}_", f"{utc_prefix}_", 1)
                    all_renames.append((old_name, new_name))
                    print(f"{old_name} -> {new_name} {prog}", file=sys.stderr)

                stats["renamed"] += 1

    # 3. Execute renames
    if all_renames and not dry_run:
        print(f"\nExecuting {len(all_renames)} renames in batches...", file=sys.stderr, flush=True)

        for batch_start in range(0, len(all_renames), batch_size):
            batch = all_renames[batch_start:batch_start + batch_size]

            # gsutil mv doesn't support multiple pairs directly, so use subprocess per pair
            # but we can parallelize with gsutil -m by writing a manifest or using xargs
            # For now, just do them with gsutil -m mv in groups

            for old_name, new_name in batch:
                subprocess.run(
                    ["gsutil", "mv", f"{data_path}/{old_name}", f"{data_path}/{new_name}"],
                    capture_output=True
                )

            print(f"  Renamed batch {batch_start//batch_size + 1} ({len(batch)} files)", file=sys.stderr)

    # Summary
    print(f"\n{'='*50}", file=sys.stderr)
    print(f"Summary:", file=sys.stderr)
    print(f"  {'Would rename' if dry_run else 'Renamed'}: {stats['renamed']} emails ({len(all_renames)} files)", file=sys.stderr)
    print(f"  Skipped (already UTC): {stats['skipped']}", file=sys.stderr)
    print(f"  Errors: {stats['error']}", file=sys.stderr)


def run_local(data_path: str, dry_run: bool):
    """Process local files."""
    p = Path(data_path)
    meta_files = sorted(p.glob("*.meta"))

    total = len(meta_files)
    width = len(str(total))
    stats = {"renamed": 0, "skipped": 0, "error": 0}

    print(f"Found {total} emails", file=sys.stderr)

    for i, meta_path in enumerate(meta_files, 1):
        prog = f"[{i:0{width}d}/{total:0{width}d} ({(i*100)//total}%)]"

        content = meta_path.read_text(encoding="utf-8")
        email_dt = parse_date_from_content(content)

        if not email_dt:
            print(f"ERROR: {meta_path.name} - no date {prog}", file=sys.stderr)
            stats["error"] += 1
            continue

        stem = meta_path.stem
        parts = stem.split("_", 1)
        if len(parts) != 2:
            print(f"ERROR: {meta_path.name} - bad format {prog}", file=sys.stderr)
            stats["error"] += 1
            continue

        current_prefix, msg_id = parts
        utc_prefix = compute_utc_prefix(email_dt)

        if current_prefix == utc_prefix:
            print(f"{meta_path.name} (no change) {prog}", file=sys.stderr)
            stats["skipped"] += 1
            continue

        # Find and rename all related files
        related = list(p.glob(f"{current_prefix}_{msg_id}.*"))
        for old_path in related:
            new_name = old_path.name.replace(f"{current_prefix}_", f"{utc_prefix}_", 1)
            new_path = p / new_name
            print(f"{old_path.name} -> {new_name} {prog}", file=sys.stderr)
            if not dry_run:
                old_path.rename(new_path)

        stats["renamed"] += 1

    print(f"\n{'='*50}", file=sys.stderr)
    print(f"Summary:", file=sys.stderr)
    print(f"  {'Would rename' if dry_run else 'Renamed'}: {stats['renamed']}", file=sys.stderr)
    print(f"  Skipped (already UTC): {stats['skipped']}", file=sys.stderr)
    print(f"  Errors: {stats['error']}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Migrate email filenames to UTC.")
    parser.add_argument("path", nargs="?", help="Local dir or gs:// path")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be renamed")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch size for GCS ops (default: 50)")
    args = parser.parse_args()

    data_path = args.path or get_default_path()

    print(f"Path: {data_path}", file=sys.stderr)
    print(f"Mode: {'DRY RUN' if args.dry_run else 'APPLY'}", file=sys.stderr)

    if is_gcs_path(data_path):
        run_gcs_batched(data_path, args.batch_size, args.dry_run)
    else:
        if not Path(data_path).exists():
            print(f"ERROR: {data_path} not found", file=sys.stderr)
            sys.exit(1)
        run_local(data_path, args.dry_run)


if __name__ == "__main__":
    main()

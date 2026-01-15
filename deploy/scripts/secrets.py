#!/usr/bin/env python3
"""
Manage Cloud Run secrets. Stdlib only.

Usage:
    ./cloud secrets list
    ./cloud secrets show gemini-api-key
"""
import argparse
import hashlib
import json
import sys

from _common import load_settings, get_cloud_provider, error, success


REQUIRED_SECRETS = ["gemini-api-key", "gmail-token"]


def cmd_list(args, provider, project_id):
    """List metadata for required cloud secrets."""
    results = []

    for sid in REQUIRED_SECRETS:
        val = provider.get_secret_value(project_id, sid)
        if val:
            results.append({
                "secret_id": sid,
                "status": "PRESENT",
                "length": len(val),
                "sha256": hashlib.sha256(val.encode() if isinstance(val, str) else val).hexdigest()
            })
        else:
            results.append({
                "secret_id": sid,
                "status": "MISSING"
            })

    if args.format == "json":
        print(json.dumps(results, indent=2))
    else:
        print(f"Secrets in project: {project_id}\n")
        for r in results:
            status = r["status"]
            if status == "PRESENT":
                print(f"  {r['secret_id']:20} PRESENT  len={r['length']:5}  sha256={r['sha256'][:16]}...")
            else:
                print(f"  {r['secret_id']:20} MISSING")


def cmd_show(args, provider, project_id):
    """Show details for a specific secret."""
    sid = args.secret_id
    val = provider.get_secret_value(project_id, sid)

    if not val:
        error(f"Secret '{sid}' not found.")
        sys.exit(1)

    val_bytes = val.encode() if isinstance(val, str) else val

    print(f"Secret:  {sid}")
    print(f"Status:  PRESENT")
    print(f"Length:  {len(val_bytes)}")
    print(f"SHA256:  {hashlib.sha256(val_bytes).hexdigest()}")


def main(args=None):
    parser = argparse.ArgumentParser(description="Manage Cloud Run secrets")
    subparsers = parser.add_subparsers(dest="action", help="Action to perform")

    # list
    list_parser = subparsers.add_parser("list", help="List required secrets")
    list_parser.add_argument("--format", choices=["table", "json"], default="table")

    # show
    show_parser = subparsers.add_parser("show", help="Show secret details")
    show_parser.add_argument("secret_id", choices=REQUIRED_SECRETS, help="Secret ID")

    parsed = parser.parse_args(args)

    if not parsed.action:
        parser.print_help()
        sys.exit(1)

    # Load config
    settings = load_settings()
    project_id = settings.get("project_id")
    if not project_id:
        error("project_id not set. Run: ./cloud init --project=YOUR_PROJECT")
        sys.exit(1)

    provider = get_cloud_provider()

    # Dispatch
    actions = {
        "list": cmd_list,
        "show": cmd_show,
    }
    actions[parsed.action](parsed, provider, project_id)


if __name__ == "__main__":
    main()

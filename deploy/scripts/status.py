#!/usr/bin/env python3
"""
Show cloud environment status. Stdlib only.

Usage:
    ./cloud status
    ./cloud status --format=json
"""
import argparse
import json
import sys

from _common import (
    load_settings, get_cloud_provider, read_cloud_status,
    format_status_table, error
)


def main(args=None):
    parser = argparse.ArgumentParser(
        description="Show cloud environment status (read-only)"
    )
    parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format"
    )

    parsed = parser.parse_args(args)

    settings = load_settings()
    project_id = settings.get("project_id")
    bucket_name = settings.get("bucket_name")

    if not project_id:
        error("project_id not set. Run: ./cloud init --project=YOUR_PROJECT")
        sys.exit(1)

    provider = get_cloud_provider()
    status = read_cloud_status(provider, project_id, bucket_name)
    status.config_saved = True

    if parsed.format == "json":
        print(json.dumps(status.to_dict(), indent=2))
    else:
        print(format_status_table(status))


if __name__ == "__main__":
    main()

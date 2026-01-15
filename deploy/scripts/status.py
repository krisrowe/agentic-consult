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

from _common import read_cloud_status, format_status_table


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

    status = read_cloud_status()

    if parsed.format == "json":
        print(json.dumps(status.to_dict(), indent=2))
    else:
        print(format_status_table(status))


if __name__ == "__main__":
    main()

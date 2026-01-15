#!/usr/bin/env python3
"""
Check deploy readiness and output terraform commands. Stdlib only.

Usage:
    ./cloud pre-deploy
    ./cloud pre-deploy --format=json
"""
import argparse
import json
import sys

from _common import (
    load_settings, get_cloud_provider, pre_deploy,
    format_status_table, error, success
)


def main(args=None):
    parser = argparse.ArgumentParser(
        description="Check deploy readiness and output terraform commands"
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format"
    )

    parsed = parser.parse_args(args)

    settings = load_settings()
    project_id = settings.get("project_id")
    bucket_name = settings.get("bucket_name")

    if not project_id:
        error("project_id not set. Run: ./cloud init --project=YOUR_PROJECT")
        sys.exit(1)
    if not bucket_name:
        error("bucket_name not set. Run: ./cloud init --project=YOUR_PROJECT --bucket=YOUR_BUCKET")
        sys.exit(1)

    provider = get_cloud_provider()
    result = pre_deploy(provider, project_id, bucket_name)

    if parsed.format == "json":
        print(json.dumps(result.to_dict(), indent=2))
        if not result.ready:
            sys.exit(1)
        return

    # Text format
    print(format_status_table(result.status))
    print()

    if not result.ready:
        error("Fix the issues above before deploying.")
        sys.exit(1)

    success("Ready to deploy. Run:\n")
    for cmd in result.terraform_commands:
        print(f"  {cmd}")
    print()


if __name__ == "__main__":
    main()

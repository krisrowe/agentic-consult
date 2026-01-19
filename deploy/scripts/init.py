#!/usr/bin/env python3
"""
Initialize cloud environment. Stdlib only.

Usage:
    ./cloud init --project=my-project
    ./cloud init --project=my-project --bucket=my-bucket
    ./cloud init --non-interactive
"""
import argparse
import json
import sys
from pathlib import Path

from _common import (
    load_settings, save_settings, get_cloud_provider,
    format_status_table, error, success, prompt, confirm,
)

# Import SDK init
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from agentic_consult.cloud import cloud_init, InitOptions, InitContext


def main(args=None):
    parser = argparse.ArgumentParser(
        description="Initialize cloud environment with strict safety"
    )
    parser.add_argument("--project", help="GCP Project ID")
    parser.add_argument("--bucket", help="Target bucket name")
    parser.add_argument("--gemini-api-key", help="Gemini API Key string")
    parser.add_argument("--gmail-token-path", help="Path to gmail token.json file")
    parser.add_argument(
        "--allow-create-bucket",
        action="store_true",
        help="Permit bucket creation"
    )
    parser.add_argument(
        "--allow-change-bucket",
        action="store_true",
        help="Permit switching labels between buckets"
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Fail instead of prompting"
    )
    parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format"
    )

    parsed = parser.parse_args(args)

    # Build SDK options
    options = InitOptions(
        project=parsed.project,
        bucket=parsed.bucket,
        gemini_api_key=parsed.gemini_api_key,
        gmail_token_path=parsed.gmail_token_path,
        allow_create_bucket=parsed.allow_create_bucket,
        allow_change_bucket=parsed.allow_change_bucket,
    )

    # Build context with interactive callbacks (or None for non-interactive)
    if parsed.non_interactive:
        context = InitContext()  # All callbacks return None/False
    else:
        def log_fn(msg):
            if parsed.format == "json":
                print(msg, file=sys.stderr)
            else:
                print(msg)

        context = InitContext(
            prompt_secret=lambda msg: prompt(msg, hide_input=True),
            prompt_path=lambda msg: prompt(msg),
            confirm=confirm,
            log=log_fn,
        )

    # Call SDK
    provider = get_cloud_provider()
    existing_config = load_settings()

    result = cloud_init(provider, options, existing_config, context)

    if not result.success:
        error(result.error)
        sys.exit(1)

    # Save config on success
    save_settings({"project_id": result.project_id, "bucket_name": result.bucket_name})

    if parsed.format == "json":
        print(json.dumps(result.to_dict(), indent=2))
    else:
        success("Cloud environment initialized.\n")
        print(format_status_table(result.status))


if __name__ == "__main__":
    main()

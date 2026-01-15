#!/usr/bin/env python3
"""
Initialize cloud environment. Stdlib only.

Usage:
    ./cloud init --project=my-project
    ./cloud init --project=my-project --bucket=my-bucket
    ./cloud init --project=my-project --non-interactive
    ./cloud init --project=my-project --gemini-api-key=KEY --gmail-token-path=token.json
"""
import argparse
import json
import sys
from pathlib import Path

from _common import (
    load_settings, save_settings, get_cloud_provider, read_cloud_status,
    format_status_table, error, success, warn, prompt, confirm,
    APP_SLUG
)


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

    provider = get_cloud_provider()
    existing_config = load_settings()

    # --- PHASE 1: VERIFICATION (READ-ONLY) ---

    # 1. Resolve Project: --project flag > existing config > label discovery
    project_id = (
        parsed.project or
        existing_config.get("project_id") or
        provider.lookup_project_by_label(APP_SLUG, "default")
    )

    if not project_id:
        error("Could not determine Project ID. Pass --project or label your project.")
        sys.exit(1)

    # 2. Validate project exists (if from config, might be stale/inaccessible)
    if not parsed.project and existing_config.get("project_id"):
        if not provider.project_exists(project_id):
            error(f"Configured project '{project_id}' not found or not accessible.")
            warn("Verify your access to this project, or use --project to specify a different one.")
            sys.exit(1)

    # 3. Validate Gemini API Key
    api_key_value = parsed.gemini_api_key
    if not provider.secret_exists(project_id, "gemini-api-key") and not api_key_value:
        if parsed.non_interactive:
            error("'gemini-api-key' secret missing and --non-interactive set.")
            sys.exit(1)
        api_key_value = prompt("Required Secret 'gemini-api-key' is missing. Enter value", hide_input=True)

    # 4. Validate Gmail Token
    token_data = None
    gmail_token_path = parsed.gmail_token_path
    if not provider.secret_exists(project_id, "gmail-token") and not gmail_token_path:
        if parsed.non_interactive:
            error("'gmail-token' secret missing and --non-interactive set.")
            sys.exit(1)
        gmail_token_path = prompt("Required Secret 'gmail-token' is missing. Enter path to token.json file")

    if gmail_token_path:
        path = Path(gmail_token_path).expanduser()
        if not path.exists():
            error(f"Gmail token file not found at {path}")
            sys.exit(1)
        token_data = path.read_bytes()

    # 5. Validate Bucket Logic
    labeled_bucket = provider.lookup_bucket_by_label(project_id, APP_SLUG, "default")
    target_bucket = parsed.bucket or labeled_bucket or f"consult-data-{project_id}"

    do_unlabel_old = False
    if labeled_bucket and parsed.bucket and labeled_bucket != parsed.bucket:
        if not parsed.allow_change_bucket:
            if parsed.non_interactive:
                error(f"Bucket '{labeled_bucket}' is already active. Pass --allow-change-bucket.")
                sys.exit(1)
            if not confirm(f"Bucket '{labeled_bucket}' is active. Switch label to '{parsed.bucket}'?"):
                print("Aborted.")
                sys.exit(1)
        do_unlabel_old = True

    do_create_bucket = False
    if not provider.bucket_exists(project_id, target_bucket):
        if not parsed.allow_create_bucket:
            if parsed.non_interactive:
                error(f"Bucket '{target_bucket}' does not exist. Pass --allow-create-bucket.")
                sys.exit(1)
            if not confirm(f"Bucket '{target_bucket}' does not exist. Create it?"):
                print("Aborted.")
                sys.exit(1)
        do_create_bucket = True

    # --- PHASE 2: EXECUTION (WRITE-ONLY) ---
    # Track operations for JSON output
    ops = []

    # Progress messages go to stderr when json format
    def log(msg):
        if parsed.format == "json":
            print(msg, file=sys.stderr)
        else:
            print(msg)

    log(f"Applying changes to project: {project_id}...")

    # 1. Handle Bucket
    if do_unlabel_old:
        log(f"Unlabeling {labeled_bucket}...")
        provider.remove_bucket_labels(labeled_bucket, [APP_SLUG])
        ops.append({"op": "bucket_unlabeled", "bucket": labeled_bucket})

    if do_create_bucket:
        log(f"Creating gs://{target_bucket}...")
        provider.create_bucket(project_id, target_bucket)
        ops.append({"op": "bucket_created", "bucket": target_bucket})

    # Only label if not already labeled (labeled_bucket == target_bucket means already labeled)
    if labeled_bucket != target_bucket:
        log(f"Ensuring {target_bucket} is labeled...")
        provider.update_bucket_labels(target_bucket, {APP_SLUG: "default"})
        ops.append({"op": "bucket_labeled", "bucket": target_bucket})

    # 2. Handle Secrets
    if api_key_value:
        if not provider.secret_exists(project_id, "gemini-api-key"):
            log("Creating secret 'gemini-api-key'...")
            provider.create_secret(project_id, "gemini-api-key", api_key_value.encode())
            ops.append({"op": "secret_created", "secret": "gemini-api-key"})
        else:
            log("Updating secret 'gemini-api-key'...")
            provider.add_secret_version(project_id, "gemini-api-key", api_key_value.encode())
            ops.append({"op": "secret_updated", "secret": "gemini-api-key"})

    if token_data:
        if not provider.secret_exists(project_id, "gmail-token"):
            log("Creating secret 'gmail-token'...")
            provider.create_secret(project_id, "gmail-token", token_data)
            ops.append({"op": "secret_created", "secret": "gmail-token"})
        else:
            log("Updating secret 'gmail-token'...")
            provider.add_secret_version(project_id, "gmail-token", token_data)
            ops.append({"op": "secret_updated", "secret": "gmail-token"})

    # 3. Save Config
    save_settings({"project_id": project_id, "bucket_name": target_bucket})

    if parsed.format != "json":
        success("Cloud environment initialized.\n")

    # 4. Show status
    status = read_cloud_status(provider, project_id, target_bucket)
    status.config_saved = True

    if parsed.format == "json":
        result = status.to_dict()
        result["operations"] = ops
        print(json.dumps(result, indent=2))
    else:
        print(format_status_table(status))


if __name__ == "__main__":
    main()

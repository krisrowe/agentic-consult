#!/usr/bin/env python3
"""
Manage user authentication for remote MCP server. Stdlib only.

These are ADMIN commands for managing server-side credentials.
Users import credentials via: consult remote auth import

Usage:
    ./cloud user-auth status            Show current auth state
    ./cloud user-auth init              Create new access token in Secret Manager
    ./cloud user-auth regen             Rotate access token (prompts unless --force)
    ./cloud user-auth export            Output URL + token as YAML for user import

Workflow:
    1. Admin: ./cloud user-auth init              # One-time setup
    2. Admin: ./cloud user-auth export > creds.yaml
    3. Admin sends creds.yaml to user (Slack, email, etc.)
    4. User:  cat creds.yaml | consult remote auth import
    5. User:  consult remote test
"""
import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys

from _common import load_settings, get_cloud_provider, error, success, warn, confirm

# Secret Manager key for MCP access token
SECRET_ID = "mcp-access-token"


def get_cloud_run_url(project_id: str) -> str:
    """Discover Cloud Run service URL via gcloud."""
    try:
        result = subprocess.run(
            ["gcloud", "run", "services", "describe", "consult-mcp",
             f"--project={project_id}", "--region=us-central1",
             "--format=value(status.url)"],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None
    except FileNotFoundError:
        error("gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install")
        sys.exit(1)


def generate_token(length: int = 32) -> str:
    """Generate a secure random token (urlsafe base64 encoded)."""
    # Using os.urandom + base64 directly to avoid collision with local secrets.py
    return base64.urlsafe_b64encode(os.urandom(length)).rstrip(b"=").decode("ascii")


def cmd_status(args, provider, project_id):
    """Show current auth state."""
    print(f"Project: {project_id}\n")

    # Check token in Secret Manager
    token = provider.get_secret_value(project_id, SECRET_ID)
    if token:
        token_bytes = token.encode() if isinstance(token, str) else token
        print(f"Token:   PRESENT")
        print(f"Length:  {len(token_bytes)}")
        print(f"SHA256:  {hashlib.sha256(token_bytes).hexdigest()[:16]}...")
    else:
        print(f"Token:   MISSING")
        print()
        warn("Run: ./cloud user-auth init")
        return

    # Check Cloud Run URL
    print()
    url = get_cloud_run_url(project_id)
    if url:
        print(f"URL:     {url}")
    else:
        print(f"URL:     NOT DEPLOYED")
        warn("Deploy with: ./cloud deploy")


def cmd_init(args, provider, project_id):
    """Create new access token in Secret Manager."""
    # Check if token already exists
    existing = provider.get_secret_value(project_id, SECRET_ID)
    if existing and not args.force:
        error("Token already exists. Use --force to overwrite, or 'regen' to rotate.")
        sys.exit(1)

    # Generate and store token
    token = generate_token()

    try:
        provider.set_secret_value(project_id, SECRET_ID, token)
        success(f"Created access token in Secret Manager: {SECRET_ID}")
        print(f"Token:   {token[:8]}...")
        print()
        print("Next steps:")
        print("  1. Deploy MCP service: ./cloud deploy")
        print("  2. Export credentials: ./cloud user-auth export")
    except Exception as e:
        error(f"Failed to create secret: {e}")
        sys.exit(1)


def cmd_regen(args, provider, project_id):
    """Rotate access token."""
    # Check if token exists
    existing = provider.get_secret_value(project_id, SECRET_ID)
    if not existing:
        error("No existing token. Use 'init' to create one first.")
        sys.exit(1)

    # Confirm unless --force
    if not args.force:
        print("This will invalidate the current token.")
        print("All users will need to re-import credentials.")
        print()
        if not confirm("Regenerate token?", default=False):
            print("Aborted.")
            sys.exit(0)

    # Generate and store new token
    token = generate_token()

    try:
        provider.set_secret_value(project_id, SECRET_ID, token)
        success("Rotated access token.")
        print(f"New token: {token[:8]}...")
        print()
        print("Next: ./cloud user-auth export  (distribute to users)")
    except Exception as e:
        error(f"Failed to update secret: {e}")
        sys.exit(1)


def cmd_export(args, provider, project_id):
    """Output URL + token as YAML for user import.

    Output format matches what 'consult remote auth import' expects:
        url: https://...
        access_token: abc123...
    """
    # Get token
    token = provider.get_secret_value(project_id, SECRET_ID)
    if not token:
        error("No access token found. Run: ./cloud user-auth init")
        sys.exit(1)

    # Get URL
    url = get_cloud_run_url(project_id)
    if not url:
        error("Cloud Run service not deployed. Run: ./cloud deploy")
        sys.exit(1)

    # Output format
    if args.format == "json":
        output = json.dumps({"url": url, "access_token": token}, indent=2)
    else:
        # YAML format (simple, no pyyaml needed)
        output = f"url: {url}\naccess_token: {token}"

    print(output)

    # Guidance to stderr (so piping works cleanly)
    if not args.quiet:
        print("\n# Pipe to user: ./cloud user-auth export | consult remote auth import", file=sys.stderr)
        print("# Or save to file: ./cloud user-auth export > creds.yaml", file=sys.stderr)


def main(args=None):
    parser = argparse.ArgumentParser(
        description="Manage user authentication for remote MCP server",
        epilog="""
Workflow:
  1. Admin: ./cloud user-auth init         # Create token
  2. Admin: ./cloud user-auth export       # Get credentials
  3. User:  consult remote auth import     # Import credentials
  4. User:  consult remote status --test   # Verify connection
        """
    )
    subparsers = parser.add_subparsers(dest="action", help="Action to perform")

    # status
    subparsers.add_parser("status", help="Show current auth state")

    # init
    init_parser = subparsers.add_parser("init", help="Create new access token")
    init_parser.add_argument("--force", action="store_true",
                            help="Overwrite existing token without prompt")

    # regen
    regen_parser = subparsers.add_parser("regen", help="Rotate access token")
    regen_parser.add_argument("--force", action="store_true",
                             help="Skip confirmation prompt")

    # export
    export_parser = subparsers.add_parser("export", help="Output credentials for user import")
    export_parser.add_argument("--format", choices=["yaml", "json"], default="yaml",
                              help="Output format (default: yaml)")
    export_parser.add_argument("-q", "--quiet", action="store_true",
                              help="Suppress guidance messages")

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
        "status": cmd_status,
        "init": cmd_init,
        "regen": cmd_regen,
        "export": cmd_export,
    }
    actions[parsed.action](parsed, provider, project_id)


if __name__ == "__main__":
    main()

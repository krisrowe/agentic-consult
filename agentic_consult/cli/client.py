"""MCP client CLI commands."""

import json
import sys
import urllib.request
import urllib.error

import click
import yaml

from agentic_consult.config import get_consult_config_dir, backup_config_file
from agentic_consult.sdk.mcp_client import get_email_stats
from agentic_consult.sdk.remote import get_remote_config

EMAIL_RULES_FILE = "email.yaml"


@click.group("client")
def client():
    """MCP client operations (local or remote)."""
    pass


@client.command("email-rules")
@click.argument("action", type=click.Choice(["push", "pull"]))
def email_rules_cmd(action: str):
    """Sync email rules between local and remote.

    ACTION is 'push' (local → remote) or 'pull' (remote → local).

    \b
    Examples:
        consult client email-rules push   # Upload local email.yaml to remote
        consult client email-rules pull   # Download remote email.yaml to local
    """
    cfg = get_remote_config()
    if not cfg.is_configured:
        click.secho("Error: Remote not configured. Run 'consult remote auth import' first.", fg="red")
        sys.exit(1)

    local_path = get_consult_config_dir() / EMAIL_RULES_FILE
    api_url = f"{cfg.url.rstrip('/')}/user/email-rules"

    if action == "push":
        if not local_path.exists():
            click.secho(f"Error: Local file not found: {local_path}", fg="red")
            sys.exit(1)

        with open(local_path, 'r', encoding='utf-8') as f:
            content = f.read()

        click.echo(f"Pushing {local_path} → remote")
        req = urllib.request.Request(api_url, method="POST")
        req.add_header("Authorization", f"Bearer {cfg.access_token}")
        req.add_header("Content-Type", "application/x-yaml")
        req.data = content.encode('utf-8')

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                if result.get("status") == "unchanged":
                    click.echo("No changes (content identical)")
                else:
                    click.secho("OK", fg="green")
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')
            click.secho(f"Error {e.code}: {body}", fg="red")
            sys.exit(1)
        except urllib.error.URLError as e:
            click.secho(f"Error: {e.reason}", fg="red")
            sys.exit(1)

    elif action == "pull":
        click.echo(f"Pulling remote → {local_path}")

        req = urllib.request.Request(api_url, method="GET")
        req.add_header("Authorization", f"Bearer {cfg.access_token}")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                remote_data = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')
            click.secho(f"Error {e.code}: {body}", fg="red")
            sys.exit(1)
        except urllib.error.URLError as e:
            click.secho(f"Error: {e.reason}", fg="red")
            sys.exit(1)

        # Check if content unchanged
        if local_path.exists():
            with open(local_path, 'r', encoding='utf-8') as f:
                local_data = yaml.safe_load(f) or {}
            if local_data == remote_data:
                click.echo("No changes (content identical)")
                return

            # Backup existing file
            backup_path = backup_config_file(local_path)
            if backup_path:
                click.echo(f"Backed up to {backup_path}", err=True)

        # Write new content
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(remote_data, f, default_flow_style=False, sort_keys=False)
        click.secho("OK", fg="green")


@client.command("get-email-stats")
@click.argument("mode", type=click.Choice(["local", "remote"]))
def get_email_stats_cmd(mode: str):
    """Get email triage stats from MCP server.

    MODE is 'local' (stdio) or 'remote' (HTTP).

    \b
    Examples:
        consult client get-email-stats local
        consult client get-email-stats remote
    """
    click.echo(f"Fetching stats from {mode} MCP server...")
    click.echo()

    result = get_email_stats(mode=mode)

    if "error" in result:
        click.secho(f"Error: {result['error']}", fg="red")
        sys.exit(1)

    # Format stats
    emails = result.get("emails", {})
    fetched = emails.get("fetched", {}).get("count", 0)
    analyzed = emails.get("analyzed", {}).get("count", 0)
    active_data = emails.get("active", {})
    active = active_data.get("count", 0)
    sample = active_data.get("sample", {})

    click.echo(f"Fetched:  {fetched}")
    click.echo(f"Analyzed: {analyzed}")
    click.echo(f"Active:   {active}")

    if sample:
        click.echo()
        click.echo("Sample breakdown:")
        for key, val in sample.items():
            if key != "size":
                click.echo(f"  {key}: {val}")

    click.echo()
    click.secho("OK", fg="green")

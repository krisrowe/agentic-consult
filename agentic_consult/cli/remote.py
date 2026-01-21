"""CLI for remote MCP server operations.

Commands for connecting to a cloud-hosted MCP server. These commands
do NOT require the repo or gcloud - just pipx install agentic-consult.

Workflow:
---------
1. Server admin runs: ./cloud user-auth export > config.yaml
2. Admin sends config.yaml to user (email, Slack, etc.)
3. User runs: cat config.yaml | consult remote auth import
4. User validates: consult remote test
5. User registers: consult remote register claude

See also:
- ./cloud user-auth --help  (admin commands, requires repo + gcloud)
"""

import click
import json
import sys

from agentic_consult.sdk.remote import (
    get_remote_config,
    set_remote_config,
    get_full_status,
    get_registration_info,
    RemoteConfig,
)
from agentic_consult.sdk.remote.config import migrate_legacy_config


@click.group()
def remote():
    """Remote MCP server configuration and status.

    \b
    These commands configure your connection to a cloud-hosted MCP server.
    For server administration, use ./cloud user-auth commands instead.

    \b
    Quick Start:
        1. Get config from admin: cat config.yaml | consult remote auth import
        2. Verify connection:      consult remote test
        3. View registration cmds: consult remote show --include-token
    """
    pass


# --- Auth subgroup ---

@remote.group()
def auth():
    """Manage authentication credentials.

    \b
    Import credentials exported by server admin:
        ./cloud user-auth export | consult remote auth import

    Or from a file:
        cat config.yaml | consult remote auth import
    """
    pass


@auth.command("import")
def auth_import():
    """Import credentials from stdin (YAML or JSON).

    \b
    The server admin generates credentials with:
        ./cloud user-auth export > config.yaml

    Then sends config.yaml to you. Import with:
        cat config.yaml | consult remote auth import

    Or pipe directly (same machine):
        ./cloud user-auth export | consult remote auth import

    \b
    Expected format:
        url: https://consult-mcp-xxx.run.app
        access_token: abc123...
    """
    # Check for legacy config and migrate
    if migrate_legacy_config():
        click.echo("Migrated legacy config to new format.")

    # Read from stdin
    data = sys.stdin.read().strip()
    if not data:
        click.secho("Error: No input received. Pipe credentials via stdin.", fg="red")
        click.echo()
        click.echo("Usage:")
        click.echo("  cat config.yaml | consult remote auth import")
        click.echo("  ./cloud user-auth export | consult remote auth import")
        sys.exit(1)

    # Parse YAML or JSON
    try:
        config = json.loads(data)
    except json.JSONDecodeError:
        # Simple YAML parsing (no pyyaml dependency)
        config = {}
        for line in data.split('\n'):
            line = line.strip()
            if ':' in line and not line.startswith('#'):
                key, value = line.split(':', 1)
                config[key.strip()] = value.strip().strip('"').strip("'")

    # Validate required fields
    url = config.get("url")
    token = config.get("access_token")

    if not url:
        click.secho("Error: 'url' not found in input.", fg="red")
        sys.exit(1)
    if not token:
        click.secho("Error: 'access_token' not found in input.", fg="red")
        sys.exit(1)

    # Save to config
    set_remote_config(url=url, access_token=token)

    click.secho("Credentials imported.", fg="green")
    click.echo(f"URL:   {url}")
    click.echo(f"Token: {token[:8]}...")
    click.echo()
    click.echo("Next: consult remote test")


@auth.command("show")
@click.option("--include-token", is_flag=True, help="Show full token (masked by default)")
def auth_show(include_token: bool):
    """Show current authentication credentials."""
    config = get_remote_config()

    if not config.url and not config.access_token:
        click.echo("No credentials configured.")
        click.echo()
        click.echo("Import with: cat config.yaml | consult remote auth import")
        sys.exit(1)

    click.echo(f"URL:   {config.url or '(not set)'}")
    if config.access_token:
        token_display = config.access_token if include_token else config.masked_token
        click.echo(f"Token: {token_display}")
    else:
        click.echo("Token: (not set)")


# --- Config subgroup ---

@remote.group()
def config():
    """Manage remote server configuration."""
    pass


@config.command("set")
@click.argument("key", type=click.Choice(["url"]))
@click.argument("value")
def config_set(key: str, value: str):
    """Set a configuration value.

    \b
    Examples:
        consult remote config set url https://consult-mcp-xxx.run.app
    """
    if key == "url":
        set_remote_config(url=value)
        click.echo(f"Set remote.url = {value}")


@config.command("show")
def config_show():
    """Show current remote configuration."""
    cfg = get_remote_config()
    click.echo("Remote Configuration")
    click.echo("────────────────────")
    click.echo(f"URL:   {cfg.url or '(not set)'}")
    click.echo(f"Token: {cfg.masked_token or '(not set)'}")

    if not cfg.is_configured:
        click.echo()
        click.secho("Not fully configured.", fg="yellow")
        click.echo("Import credentials: cat config.yaml | consult remote auth import")


# --- Show command ---

@remote.command("show")
@click.option("--include-token", is_flag=True, help="Show full token (masked by default)")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def show(include_token: bool, output_format: str):
    """Show remote server configuration and registration commands.

    \b
    Displays:
    - Current URL and token (masked by default)
    - Commands to register with Claude and Gemini
    - Manual registration info for other MCP clients

    \b
    Examples:
        consult remote show
        consult remote show --include-token
        consult remote show --format json
    """
    # Check for legacy config and migrate
    if migrate_legacy_config():
        click.echo("Migrated legacy config to new format.")
        click.echo()

    info = get_registration_info(include_token=include_token)

    if output_format == "json":
        click.echo(json.dumps(info, indent=2))
        if not info["configured"]:
            sys.exit(1)
        return

    # Text output
    if not info["configured"]:
        click.secho(info["error"], fg="red")
        sys.exit(1)

    click.echo("Remote Configuration")
    click.echo("────────────────────")
    click.echo(f"URL:   {info['config']['url']}")
    click.echo(f"Token: {info['config']['token_masked']} ✓")

    click.echo()
    click.echo("Register with Claude:")
    click.echo(f"  {info['commands']['claude']}")

    click.echo()
    click.echo("Register with Gemini:")
    click.echo(f"  {info['commands']['gemini']}")

    click.echo()
    click.echo("Other MCP clients:")
    click.echo("  Option 1 (header auth - preferred):")
    click.echo(f"    URL:    {info['manual']['header_auth']['url']}")
    click.echo(f"    Header: {info['manual']['header_auth']['header']}")
    click.echo()
    click.echo("  Option 2 (query string auth):")
    click.echo(f"    URL:    {info['manual']['query_auth']['url']}")

    if not include_token:
        click.echo()
        click.secho("Use --include-token to reveal full token in commands.", fg="yellow")


# --- Test command ---

@remote.command("test")
def test():
    """Test connectivity and authentication to remote server.

    \b
    Validates:
        1. Service reachable (health check)
        2. Token valid (auth check)
        3. Tool access (optional email stats)

    \b
    Use before registering with Claude/Gemini to ensure connection works.

    \b
    Examples:
        consult remote test
        consult remote test && consult remote register claude
    """
    # Check for legacy config and migrate
    if migrate_legacy_config():
        click.echo("Migrated legacy config to new format.")
        click.echo()

    cfg = get_remote_config()

    if not cfg.is_configured:
        click.secho("Error: Not configured. Run 'consult remote auth import' first.", fg="red")
        sys.exit(1)

    click.echo("Testing connection...")
    click.echo(f"URL:   {cfg.url}")
    click.echo()

    remote_status = get_full_status(test_tool="email_triage_stats")

    # Health
    if remote_status.health_ok:
        click.echo("Health: ✓ Service reachable")
    else:
        click.secho(f"Health: ✗ {remote_status.health_error}", fg="red")
        _show_connection_guidance()
        sys.exit(1)

    # Auth
    if remote_status.auth_ok:
        click.echo("Auth:   ✓ Token valid")
    else:
        click.secho(f"Auth:   ✗ {remote_status.auth_error}", fg="red")
        sys.exit(1)

    # Tool test
    if remote_status.tool_result:
        emails = remote_status.tool_result.get("emails", {})
        fetched = emails.get("fetched", {}).get("count", 0)
        analyzed = emails.get("analyzed", {}).get("count", 0)
        active_data = emails.get("active", {})
        active = active_data.get("count", 0)
        sample = active_data.get("sample", {})
        sample_info = ""
        if sample:
            archive = sample.get("archive", 0)
            review = sample.get("review", 0)
            sample_info = f" (sample: {archive} archive, {review} review)"
        click.echo(f"Stats:  ✓ {fetched} fetched, {analyzed} analyzed, {active} active{sample_info}")
    elif remote_status.tool_error:
        click.secho(f"Stats:  ✗ {remote_status.tool_error}", fg="yellow")
        # Not fatal - stats are optional

    click.echo()
    click.secho("Connection verified.", fg="green")


def _show_connection_guidance():
    """Show guidance when connection fails."""
    click.echo()
    click.secho("To fix:", fg="yellow")
    click.echo("  1. Deploy MCP service:  ./cloud deploy")
    click.echo("  2. Export credentials:  ./cloud user-auth export | consult remote auth import")
    click.echo()
    click.echo("  Then run: consult remote show --include-token")
    click.echo("  to see registration commands.")

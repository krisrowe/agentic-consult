"""CLI for remote MCP server operations.

Commands for connecting to a cloud-hosted MCP server. These commands
do NOT require the repo or gcloud - just pipx install agentic-consult.

Workflow:
---------
1. Server admin runs: ./cloud user-auth export > config.yaml
2. Admin sends config.yaml to user (email, Slack, etc.)
3. User runs: cat config.yaml | consult remote auth import
4. User validates: consult remote status --test
5. User registers: consult remote register claude

See also:
- ./cloud user-auth --help  (admin commands, requires repo + gcloud)
"""

import click
import json
import sys
import subprocess
import shutil

from agentic_consult.sdk.remote import (
    get_remote_config,
    set_remote_config,
    get_full_status,
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
        2. Verify connection:      consult remote status --test
        3. Register with Claude:   consult remote register claude
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
    click.echo("Next: consult remote status --test")


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


# --- Status command ---

@remote.command("status")
@click.option("--test", is_flag=True, help="Test connectivity and authentication")
def status(test: bool):
    """Show remote server status.

    \b
    Without --test:
        Shows current configuration only.

    \b
    With --test:
        Validates connectivity, authentication, and tool access.
        Use for health checks before registering with Claude/Gemini.

    \b
    Examples:
        consult remote status
        consult remote status --test
        consult remote status --test && consult remote register claude
    """
    # Check for legacy config and migrate
    if migrate_legacy_config():
        click.echo("Migrated legacy config to new format.")
        click.echo()

    cfg = get_remote_config()

    click.echo("Remote Configuration")
    click.echo("────────────────────")

    if not cfg.url:
        click.echo("URL:   (not configured)")
    else:
        click.echo(f"URL:   {cfg.url}")

    if not cfg.access_token:
        click.echo("Token: (not configured)")
    else:
        click.echo(f"Token: {cfg.masked_token} ✓")

    if not cfg.is_configured:
        click.echo()
        click.secho("Run 'consult remote auth import' to configure.", fg="yellow")
        sys.exit(1)

    if test:
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
            active = emails.get("active", {}).get("count", 0)
            click.echo(f"Stats:  ✓ {fetched} fetched, {analyzed} analyzed, {active} active")
        elif remote_status.tool_error:
            click.secho(f"Stats:  ✗ {remote_status.tool_error}", fg="yellow")
            # Not fatal - stats are optional


def _show_connection_guidance():
    """Show guidance when connection fails."""
    click.echo()
    click.secho("To fix:", fg="yellow")
    click.echo("  1. Deploy MCP service:  ./cloud deploy")
    click.echo("  2. Export credentials:  ./cloud user-auth export | consult remote auth import")
    click.echo()
    click.echo("  Or use local server:    consult remote register local claude")


# --- Register command ---

@remote.command("register")
@click.argument("target", type=click.Choice(["local", "cloud", "manual"]))
@click.argument("client", type=click.Choice(["gemini", "claude"]), required=False)
@click.option("--name", default="consult", help="Server name for registration")
@click.option("--scope", type=click.Choice(["user", "project"]), default="user", help="Where to save")
@click.option("--guide-only", is_flag=True, help="Output guidance without exit 1 (for broken combos)")
@click.option("--include-token", is_flag=True, help="Include full token in output (masked by default)")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def register(target: str, client: str, name: str, scope: str, guide_only: bool, include_token: bool, output_format: str):
    """Register MCP server with Gemini or Claude.

    \b
    Targets:
        local  - Register local stdio server (consult-mcp)
        cloud  - Register cloud HTTP server (uses configured URL)
        manual - Show URL and auth info for manual registration

    \b
    Examples:
        consult remote register local gemini
        consult remote register local claude
        consult remote register cloud claude --name my-consult
        consult remote register manual
    """
    cfg = get_remote_config()

    # Manual target: show URL info
    if target == "manual":
        if not cfg.is_configured:
            click.secho("Error: Not configured. Run 'consult remote auth import' first.", fg="red", err=True)
            sys.exit(1)

        token_display = cfg.access_token if include_token else "************"

        if output_format == "json":
            info = {
                "url": cfg.url,
                "header_auth": {
                    "url": cfg.url,
                    "header": f"Authorization: Bearer {token_display}",
                },
                "query_auth": {
                    "url": f"{cfg.url.rstrip('/')}?token={token_display}",
                },
            }
            click.echo(json.dumps(info, indent=2))
        else:
            click.echo("MCP Registration Info")
            click.echo("─────────────────────")
            click.echo()
            click.echo("Option 1 (header auth):")
            click.echo(f"  URL:    {cfg.url}")
            click.echo(f"  Header: Authorization: Bearer {token_display}")
            click.echo()
            click.echo("Option 2 (query string auth):")
            click.echo(f"  URL:    {cfg.url.rstrip('/')}?token={token_display}")
            if not include_token:
                click.echo()
                click.echo("Use --include-token to reveal full token.")
        sys.exit(0)

    # local/cloud require client argument
    if not client:
        click.secho("Error: CLIENT argument required for local/cloud targets.", fg="red", err=True)
        sys.exit(1)

    if target == "cloud":
        if not cfg.is_configured:
            click.secho("Error: Not configured. Run 'consult remote auth import' first.", fg="red", err=True)
            sys.exit(1)

    # Check CLI availability
    if client == "gemini" and not shutil.which("gemini"):
        click.secho("Error: 'gemini' CLI not found in PATH.", fg="red", err=True)
        sys.exit(1)
    elif client == "claude" and not shutil.which("claude"):
        click.secho("Error: 'claude' CLI not found in PATH.", fg="red", err=True)
        sys.exit(1)

    # Build and run command
    if target == "local":
        if client == "gemini":
            cmd = ["gemini", "mcp", "add", name, "consult-mcp", "--scope", scope]
            result = subprocess.run(cmd)
            sys.exit(result.returncode)
        elif client == "claude":
            subprocess.run(["claude", "mcp", "remove", name, "-s", scope], capture_output=True)
            cmd = ["claude", "mcp", "add", "-s", scope, name, "consult-mcp"]
            result = subprocess.run(cmd)
            sys.exit(result.returncode)

    elif target == "cloud":
        if client == "gemini":
            # Check gemini version for HTTP bug
            version_ok = True
            try:
                result = subprocess.run(["gemini", "--version"], capture_output=True, text=True)
                version_str = result.stdout.strip()
                parts = version_str.split(".")
                if len(parts) >= 2:
                    major, minor = int(parts[0]), int(parts[1])
                    version_ok = (major, minor) >= (0, 24)
            except Exception:
                pass  # Assume newer if can't check

            full_url = f'{cfg.url.rstrip("/")}?token={cfg.access_token}'

            if version_ok:
                cmd = ["gemini", "mcp", "add", name, full_url, "--scope", scope]
                result = subprocess.run(cmd)
                sys.exit(result.returncode)
            elif guide_only:
                click.echo("npm i -g @google/gemini-cli@latest")
                sys.exit(0)
            else:
                click.secho("Error: 'gemini mcp add' broken for HTTP in < v0.24.0", fg="red", err=True)
                click.secho("Upgrade: npm i -g @google/gemini-cli@latest", fg="yellow", err=True)
                sys.exit(1)

        elif client == "claude":
            subprocess.run(["claude", "mcp", "remove", name, "-s", scope], capture_output=True)
            cmd = [
                "claude", "mcp", "add",
                "--transport", "http",
                "--header", f"Authorization: Bearer {cfg.access_token}",
                "-s", scope,
                name, cfg.url
            ]
            result = subprocess.run(cmd)
            sys.exit(result.returncode)

"""CLI for MCP user operations (no gcloud required).

These commands are for MCP users who install via pipx and connect
to a cloud MCP service. They do NOT require the repo or gcloud.

Admin commands (./cloud user-auth) manage the server-side secrets.
These commands manage the client-side config.
"""

import click
import json
import sys
import urllib.request
import urllib.error
from ..config import load_main_config, set_app_config_value


@click.group()
def mcp():
    """MCP client configuration and status."""
    pass


@mcp.command("import")
def mcp_import():
    """Import MCP credentials from stdin (YAML or JSON).

    \b
    Usage:
        cat config.yaml | consult mcp import
        ./cloud user-auth export | consult mcp import

    \b
    Expected format (YAML or JSON):
        mcp_url: https://consult-mcp-xxx.run.app
        personal_access_token: abc123...
    """
    import sys

    # Read from stdin
    data = sys.stdin.read().strip()
    if not data:
        click.secho("Error: No input received. Pipe credentials via stdin.", fg="red")
        sys.exit(1)

    # Parse YAML or JSON
    try:
        # Try JSON first
        config = json.loads(data)
    except json.JSONDecodeError:
        # Try YAML (simple key: value parsing, no pyyaml dependency)
        config = {}
        for line in data.split('\n'):
            line = line.strip()
            if ':' in line and not line.startswith('#'):
                key, value = line.split(':', 1)
                config[key.strip()] = value.strip().strip('"').strip("'")

    # Validate required fields
    url = config.get("mcp_url")
    pat = config.get("personal_access_token")

    if not url:
        click.secho("Error: 'mcp_url' not found in input.", fg="red")
        sys.exit(1)
    if not pat:
        click.secho("Error: 'personal_access_token' not found in input.", fg="red")
        sys.exit(1)

    # Save to config
    set_app_config_value("mcp_url", url)
    set_app_config_value("personal_access_token", pat)

    click.secho("MCP credentials imported.", fg="green")
    click.echo(f"URL: {url}")
    click.echo(f"PAT: {pat[:8]}...")


@mcp.command("status")
@click.option("--test", is_flag=True, help="Test connectivity and auth")
def mcp_status(test: bool):
    """Show MCP configuration and optionally test connectivity.

    \b
    Examples:
        consult mcp status
        consult mcp status --test
        consult mcp status --test && consult mcp register gemini
    """
    config = load_main_config()
    url = config.get("mcp_url")
    pat = config.get("personal_access_token")

    click.echo("MCP Configuration")
    click.echo("─────────────────")

    if not url:
        click.echo("URL: (not configured)")
    else:
        click.echo(f"URL: {url}")

    if not pat:
        click.echo("PAT: (not configured)")
    else:
        click.echo(f"PAT: {pat[:8]}... ✓")

    if not url or not pat:
        click.secho("\nRun 'consult mcp import' to configure.", fg="yellow")
        sys.exit(1)

    if test:
        click.echo()
        # Test health endpoint (no auth)
        health_url = f"{url.rstrip('/')}/health"
        try:
            req = urllib.request.Request(health_url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    click.echo("Health: ✓ Service reachable")
                else:
                    click.secho(f"Health: ✗ Unexpected status {resp.status}", fg="red")
                    sys.exit(1)
        except urllib.error.URLError as e:
            click.secho(f"Health: ✗ {e.reason}", fg="red")
            sys.exit(1)
        except Exception as e:
            click.secho(f"Health: ✗ {e}", fg="red")
            sys.exit(1)

        # Test auth (call /mcp endpoint with token)
        # MCP uses POST to /mcp for the streamable HTTP transport
        # But we can test auth by hitting any authenticated endpoint
        # The simplest is to check if we get 401/403 vs success on /mcp
        mcp_url = f"{url.rstrip('/')}/mcp"
        try:
            req = urllib.request.Request(mcp_url, method="POST")
            req.add_header("Authorization", f"Bearer {pat}")
            req.add_header("Content-Type", "application/json")
            # Send minimal MCP request (will fail but auth should pass)
            req.data = b'{"jsonrpc": "2.0", "method": "initialize", "id": 1}'
            with urllib.request.urlopen(req, timeout=10) as resp:
                # Any 2xx means auth passed
                click.echo("Auth:   ✓ Token valid")
        except urllib.error.HTTPError as e:
            if e.code == 401:
                click.secho("Auth:   ✗ No token provided", fg="red")
                sys.exit(1)
            elif e.code == 403:
                click.secho("Auth:   ✗ Invalid token", fg="red")
                sys.exit(1)
            elif e.code == 500:
                click.secho("Auth:   ✗ Server misconfigured", fg="red")
                sys.exit(1)
            else:
                # Other errors (400, 404, etc.) might mean auth passed but request was bad
                # That's OK - we just want to verify auth works
                click.echo("Auth:   ✓ Token valid")
        except urllib.error.URLError as e:
            click.secho(f"Auth:   ✗ {e.reason}", fg="red")
            sys.exit(1)


@mcp.command("register")
@click.option("--name", default="consult", help="Server name for registration")
@click.option("--scope", type=click.Choice(["user", "project"]), default="user", help="Where to save")
@click.option("--run", is_flag=True, help="Execute the command instead of just showing it")
def mcp_register(name: str, scope: str, run: bool):
    """Output or run the aicfg command to register this MCP server.

    \b
    Examples:
        consult mcp register              # Show command
        consult mcp register --run        # Execute it
        consult mcp register --scope project --run
    """
    config = load_main_config()
    url = config.get("mcp_url")
    pat = config.get("personal_access_token")

    if not url or not pat:
        click.secho("Error: MCP not configured. Run 'consult mcp import' first.", fg="red")
        sys.exit(1)

    # Build URL with embedded token
    full_url = f"{url.rstrip('/')}?token={pat}"
    cmd = f'aicfg mcp add --name {name} --url "{full_url}" --scope {scope}'

    if run:
        import subprocess
        result = subprocess.run(cmd, shell=True)
        sys.exit(result.returncode)
    else:
        click.echo(cmd)

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
@click.argument("target", type=click.Choice(["local", "cloud"]))
@click.argument("client", type=click.Choice(["gemini", "claude"]))
@click.option("--name", default="consult", help="Server name for registration")
@click.option("--scope", type=click.Choice(["user", "project"]), default="user", help="Where to save")
@click.option("--guide-only", is_flag=True, help="Output guidance without exit 1 (for broken combos)")
def mcp_register(target: str, client: str, name: str, scope: str, guide_only: bool):
    """Register MCP server with Gemini or Claude.

    \b
    Targets:
        local  - Register local stdio server (consult-mcp)
        cloud  - Register cloud HTTP server (requires mcp_url config)

    \b
    Note: 'cloud gemini' requires gemini CLI >= 0.24.0 (HTTP bug fix).
    Use --guide-only to get upgrade command without exit 1.

    \b
    Examples:
        consult mcp register local gemini
        consult mcp register local claude
        consult mcp register cloud gemini --guide-only
        consult mcp register cloud claude --name my-consult
    """
    import subprocess
    import shutil

    config = load_main_config()

    if target == "cloud":
        url = config.get("mcp_url")
        pat = config.get("personal_access_token")
        if not url or not pat:
            click.secho("Error: Cloud MCP not configured. Run 'consult mcp import' first.", fg="red", err=True)
            sys.exit(1)

    # Check CLI availability
    if client == "gemini":
        if not shutil.which("gemini"):
            click.secho("Error: 'gemini' CLI not found in PATH.", fg="red", err=True)
            sys.exit(1)
    elif client == "claude":
        if not shutil.which("claude"):
            click.secho("Error: 'claude' CLI not found in PATH.", fg="red", err=True)
            sys.exit(1)

    # Build and run command
    if target == "local":
        if client == "gemini":
            # gemini mcp add is idempotent
            cmd = ["gemini", "mcp", "add", name, "consult-mcp", "--scope", scope]
            result = subprocess.run(cmd)
            sys.exit(result.returncode)

        elif client == "claude":
            # claude mcp add fails if exists, so remove first
            subprocess.run(["claude", "mcp", "remove", name, "-s", scope],
                          capture_output=True)  # ignore errors
            cmd = ["claude", "mcp", "add", "-s", scope, name, "consult-mcp"]
            result = subprocess.run(cmd)
            sys.exit(result.returncode)

    elif target == "cloud":
        if client == "gemini":
            # Check gemini version - HTTP is broken in < 0.24.0
            # See: https://github.com/google-gemini/gemini-cli/issues/16169
            # Default to True (assume newer) if version check fails
            version_ok = True
            try:
                result = subprocess.run(["gemini", "--version"], capture_output=True, text=True)
                version_str = result.stdout.strip()
                parts = version_str.split(".")
                if len(parts) >= 2:
                    major, minor = int(parts[0]), int(parts[1])
                    version_ok = (major, minor) >= (0, 24)
            except Exception as e:
                import logging
                logging.warning(f"Could not check gemini version: {e}. Assuming >= 0.24.0")

            full_url = f'{url.rstrip("/")}?token={pat}'

            if version_ok:
                # v0.24.0+ - use gemini CLI directly
                cmd = ["gemini", "mcp", "add", name, full_url, "--scope", scope]
                result = subprocess.run(cmd)
                sys.exit(result.returncode)
            elif guide_only:
                click.echo("npm i -g @google/gemini-cli@latest")
                sys.exit(0)
            else:
                click.secho("Error: 'gemini mcp add' is broken for HTTP in < v0.24.0", fg="red", err=True)
                click.secho("See: https://github.com/google-gemini/gemini-cli/issues/16169", err=True)
                click.secho("Upgrade: npm i -g @google/gemini-cli@latest", fg="yellow", err=True)
                sys.exit(1)

        elif client == "claude":
            # claude mcp add works for HTTP with headers
            subprocess.run(["claude", "mcp", "remove", name, "-s", scope],
                          capture_output=True)  # ignore errors
            cmd = [
                "claude", "mcp", "add",
                "--transport", "http",
                "--header", f"Authorization: Bearer {pat}",
                "-s", scope,
                name, url
            ]
            result = subprocess.run(cmd)
            sys.exit(result.returncode)

import click
from pathlib import Path
from agentic_consult.config import configure_workspace_context

@click.group()
def client():
    """Manage client workspace configuration."""
    pass

@client.command(name='install')
def client_install():
    """
    Bootstrap the client repository configuration.
    
    1. Injects shared CONSULT-TOOLS.md context.
    2. Registers consult-mcp server.
    3. Updates .gemini/settings.json.
    """
    repo_path = Path.cwd()
    try:
        result = configure_workspace_context(repo_path)
        click.echo(f"Client bootstrapped for repo: {repo_path}")
        click.echo(f"  - Context:  {result['installed']}")
        click.echo(f"  - Symlink:  {result['symlink']}")
        click.echo(f"  - Settings: {result['settings_updated']}")
        click.echo(f"  - Files:    {', '.join(result['filenames'])}")
        click.echo(f"  - MCP:      {result['mcp_status']}")
    except Exception as e:
        click.echo(f"Error bootstrapping client: {e}", err=True)
        click.get_current_context().exit(1)

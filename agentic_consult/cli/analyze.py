import click
import sys
from agentic_consult.analyze import run_analysis

def _print_stats(stats: dict, response_text: str, stats_enabled: bool):
    """Formats and prints analysis statistics to stderr."""
    file_count = stats.get("file_count", 0)
    total_bytes = stats.get("total_bytes", 0)
    model = stats.get("model", "unknown")
    
    if stats_enabled:
        click.echo(f"Found {file_count} file(s). Total context size: {total_bytes} bytes ({total_bytes / 1024:.2f} KB).", err=True)
        click.echo(f"Using model: {model}", err=True)
    
    click.echo(f"Analyzing {file_count} files...", err=True)

    if stats_enabled:
        resp_bytes = len(response_text.encode('utf-8'))
        click.echo(f"Response size: {resp_bytes} bytes ({resp_bytes / 1024:.2f} KB).", err=True)

@click.command()
@click.argument("prompt")
@click.option(
    "--resources", "-r", 
    default=".", 
    help="Path, glob, or comma-separated list of paths/globs (e.g., 'docs/*.md,notes/'). Defaults to '.'"
)
@click.option("--stats", "-s", "stats_enabled", is_flag=True, help="Show analysis statistics.")
def analyze(prompt, resources, stats_enabled):
    """Analyze project resources and documentation with Gemini."""
    
    # Split resources string into list
    resource_list = [item.strip() for item in resources.split(",") if item.strip()]
    if not resource_list and resources.strip():
        click.echo("Error: Resource paths cannot be empty.", err=True)
        sys.exit(1)

    result = run_analysis(prompt, resource_list)

    if result.get("error"):
        click.echo(f"Error: {result['error']}", err=True)
        sys.exit(1)

    _print_stats(result.get("stats", {}), result.get("response", ""), stats_enabled)
        
    click.echo("\n" + result.get("response", ""))

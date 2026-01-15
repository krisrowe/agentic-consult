"""CLI for building and pushing container images."""

import click
import subprocess
import sys
from pathlib import Path
from ..config import load_main_config


def run_cmd(cmd, cwd=None):
    """Run a shell command."""
    print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    subprocess.run(cmd, check=True, cwd=cwd)


@click.group()
def image():
    """Build and push container images."""
    pass


@image.command("build")
def image_build():
    """Build the consult-analyzer Docker image."""
    data = load_main_config()
    project_id = data.get("project_id")
    if not project_id:
        click.secho("Error: project_id not set. Run: consult cloud init", fg="red")
        sys.exit(1)

    img = f"gcr.io/{project_id}/consult-analyzer:latest"
    repo_root = Path(__file__).parent.parent.parent

    click.echo(f"Building {img}...")
    run_cmd(["docker", "build", "--target", "analyzer", "-t", img, "."], cwd=repo_root)
    click.secho(f"✅ Built: {img}", fg="green")


@image.command("push")
@click.argument("project_id", required=False)
def image_push(project_id: str):
    """Push the consult-analyzer image to GCR."""
    if not project_id:
        data = load_main_config()
        project_id = data.get("project_id")
    if not project_id:
        click.secho("Error: project_id required. Pass as argument or run: consult cloud init", fg="red")
        sys.exit(1)

    img = f"gcr.io/{project_id}/consult-analyzer:latest"

    click.echo(f"Pushing {img}...")
    run_cmd(["docker", "push", img])
    click.secho(f"✅ Pushed: {img}", fg="green")

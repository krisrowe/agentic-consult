#!/usr/bin/env python3
"""
Build and push container images. Stdlib only.

Usage:
    ./cloud image build
    ./cloud image push
    ./cloud image push --project=my-project
"""
import argparse
import subprocess
import sys
from pathlib import Path

from _common import load_settings, error, success, REPO_ROOT


def run_cmd(cmd, cwd=None):
    """Run a shell command."""
    print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    subprocess.run(cmd, check=True, cwd=cwd)


def cmd_build(args):
    """Build the Docker image."""
    settings = load_settings()
    project_id = args.project or settings.get("project_id")

    if not project_id:
        error("project_id not set. Run: ./cloud init --project=YOUR_PROJECT")
        sys.exit(1)

    img = f"gcr.io/{project_id}/consult-analyzer:latest"

    print(f"Building {img}...")
    run_cmd(["docker", "build", "--target", "analyzer", "-t", img, "."], cwd=REPO_ROOT)
    success(f"Built: {img}")


def cmd_push(args):
    """Push the Docker image to GCR."""
    settings = load_settings()
    project_id = args.project or settings.get("project_id")

    if not project_id:
        error("project_id not set. Pass --project or run: ./cloud init")
        sys.exit(1)

    img = f"gcr.io/{project_id}/consult-analyzer:latest"

    print(f"Pushing {img}...")
    run_cmd(["docker", "push", img])
    success(f"Pushed: {img}")


def main(args=None):
    parser = argparse.ArgumentParser(description="Build and push container images")
    subparsers = parser.add_subparsers(dest="action", help="Action to perform")

    # build
    build_parser = subparsers.add_parser("build", help="Build Docker image")
    build_parser.add_argument("--project", help="GCP Project ID (overrides config)")

    # push
    push_parser = subparsers.add_parser("push", help="Push image to GCR")
    push_parser.add_argument("--project", help="GCP Project ID (overrides config)")

    parsed = parser.parse_args(args)

    if not parsed.action:
        parser.print_help()
        sys.exit(1)

    actions = {
        "build": cmd_build,
        "push": cmd_push,
    }
    actions[parsed.action](parsed)


if __name__ == "__main__":
    main()

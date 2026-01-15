#!/usr/bin/env python3
"""
Build and push container images. Stdlib only.

Usage:
    ./cloud images list
    ./cloud images build analyzer
    ./cloud images build mcp
    ./cloud images push analyzer
    ./cloud images push mcp
"""
import argparse
import configparser
import json
import subprocess
import sys
from pathlib import Path

from _common import load_settings, error, success, warn, REPO_ROOT


def load_images_config():
    """Load image definitions from deploy/images.ini."""
    config_path = REPO_ROOT / "deploy" / "images.ini"
    parser = configparser.ConfigParser()
    parser.read(config_path)

    images = {}
    for section in parser.sections():
        images[section] = dict(parser[section])
        # Convert 'true'/'false' strings to booleans
        if "internal" in images[section]:
            images[section]["internal"] = parser.getboolean(section, "internal")
    return images


def run_cmd(cmd, cwd=None, capture=False):
    """Run a shell command."""
    if capture:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        return result
    print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    subprocess.run(cmd, check=True, cwd=cwd)


def get_local_image_info(image_tag: str) -> dict:
    """Get info about a local docker image."""
    result = run_cmd(
        ["docker", "images", "--format", "json", image_tag],
        capture=True
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None

    line = result.stdout.strip().split('\n')[0]
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def get_gcr_image_info(project_id: str, gcr_name: str) -> dict:
    """Get info about image in GCR."""
    result = run_cmd(
        ["gcloud", "container", "images", "describe",
         f"gcr.io/{project_id}/{gcr_name}:latest",
         "--format=json"],
        capture=True
    )
    if result.returncode != 0:
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def cmd_list(args):
    """List all images with their status."""
    settings = load_settings()
    project_id = args.project or settings.get("project_id")
    images = load_images_config()

    if not project_id:
        error("project_id not set. Run: ./cloud init")
        sys.exit(1)

    print(f"Images for project: {project_id}\n")
    print(f"{'Name':<12} {'Local':<20} {'GCR':<20} {'Type':<10}")
    print("-" * 62)

    for name, info in images.items():
        gcr_name = info["gcr_name"]
        is_internal = info.get("internal", True)
        image_tag = f"gcr.io/{project_id}/{gcr_name}:latest"

        # Check local
        local_info = get_local_image_info(image_tag)
        if local_info:
            created = local_info.get("CreatedAt", "")[:19]
            local_str = f"built {created}"
        else:
            local_str = "not built"

        # Check GCR
        gcr_info = get_gcr_image_info(project_id, gcr_name)
        if gcr_info:
            digest = gcr_info.get("image_summary", {}).get("digest", "")
            if digest:
                digest_short = digest.split(":")[-1][:12]
                gcr_str = f"exists ({digest_short})"
            else:
                gcr_str = "exists"
        else:
            gcr_str = "missing"

        type_str = "internal" if is_internal else "external"
        print(f"{name:<12} {local_str:<20} {gcr_str:<20} {type_str:<10}")


def cmd_build(args):
    """Build a specific Docker image."""
    images = load_images_config()

    if not args.name:
        error("Image name required. Options: " + ", ".join(images.keys()))
        sys.exit(1)

    if args.name not in images:
        error(f"Unknown image '{args.name}'. Options: " + ", ".join(images.keys()))
        sys.exit(1)

    info = images[args.name]

    # Handle external images
    if not info.get("internal", True):
        repo = Path(info["repo"]).expanduser()
        build_cmd = info.get("build_cmd", "make build")
        print(f"External image. Run in {repo}:")
        print(f"  cd {repo} && {build_cmd}")
        sys.exit(0)

    settings = load_settings()
    project_id = args.project or settings.get("project_id")

    if not project_id:
        error("project_id not set. Run: ./cloud init")
        sys.exit(1)

    gcr_name = info["gcr_name"]
    target = info["target"]
    img = f"gcr.io/{project_id}/{gcr_name}:latest"

    print(f"Building {img}...")
    run_cmd(["docker", "build", "--target", target, "-t", img, "."], cwd=REPO_ROOT)
    success(f"Built: {img}")


def cmd_push(args):
    """Push a specific Docker image to GCR."""
    images = load_images_config()

    if not args.name:
        error("Image name required. Options: " + ", ".join(images.keys()))
        sys.exit(1)

    if args.name not in images:
        error(f"Unknown image '{args.name}'. Options: " + ", ".join(images.keys()))
        sys.exit(1)

    info = images[args.name]

    # Handle external images
    if not info.get("internal", True):
        repo = Path(info["repo"]).expanduser()
        push_cmd = info.get("push_cmd", "make push")
        print(f"External image. Run in {repo}:")
        print(f"  cd {repo} && {push_cmd}")
        sys.exit(0)

    settings = load_settings()
    project_id = args.project or settings.get("project_id")

    if not project_id:
        error("project_id not set. Run: ./cloud init")
        sys.exit(1)

    gcr_name = info["gcr_name"]
    img = f"gcr.io/{project_id}/{gcr_name}:latest"

    print(f"Pushing {img}...")
    run_cmd(["docker", "push", img])
    success(f"Pushed: {img}")


def main(args=None):
    images = load_images_config()
    image_names = ", ".join(images.keys())

    parser = argparse.ArgumentParser(description="Build and push container images")
    subparsers = parser.add_subparsers(dest="action", help="Action to perform")

    # list
    list_parser = subparsers.add_parser("list", help="List images and their status")
    list_parser.add_argument("--project", help="GCP Project ID (overrides config)")

    # build
    build_parser = subparsers.add_parser("build", help="Build a Docker image")
    build_parser.add_argument("name", nargs="?", help=f"Image name: {image_names}")
    build_parser.add_argument("--project", help="GCP Project ID (overrides config)")

    # push
    push_parser = subparsers.add_parser("push", help="Push image to GCR")
    push_parser.add_argument("name", nargs="?", help=f"Image name: {image_names}")
    push_parser.add_argument("--project", help="GCP Project ID (overrides config)")

    parsed = parser.parse_args(args)

    if not parsed.action:
        parser.print_help()
        sys.exit(1)

    actions = {
        "list": cmd_list,
        "build": cmd_build,
        "push": cmd_push,
    }
    actions[parsed.action](parsed)


if __name__ == "__main__":
    main()

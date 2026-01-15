#!/usr/bin/env python3
"""
Build and push container images. Stdlib only.

Usage:
    ./cloud images list
    ./cloud images build <name>
    ./cloud images push <name>
    ./cloud images deploy <name>          # build + push
    ./cloud images deploy <name> --dry-run # show manual steps
"""
import argparse
import configparser
import json
import shutil
import subprocess
import sys
import tempfile
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
    return images


def is_internal(info: dict) -> bool:
    """Check if image is internal (built in this repo)."""
    return "target" in info


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


def get_gcr_image_info(project_id: str, image_name: str) -> dict:
    """Get info about image in GCR."""
    result = run_cmd(
        ["gcloud", "container", "images", "describe",
         f"gcr.io/{project_id}/{image_name}:latest",
         "--format=json"],
        capture=True
    )
    if result.returncode != 0:
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


# --- Commands as data (for dry-run support) ---

def get_build_commands(info: dict, project_id: str, tmp_dir: str) -> list:
    """Get build commands as list of command arrays."""
    commands = []
    img = f"gcr.io/{project_id}/{info['image']}:latest"

    if is_internal(info):
        commands.append(["docker", "build", "--target", info["target"], "-t", img, "."])
    else:
        clone = ["git", "clone", "--depth", "1"]
        if info.get("ref"):
            clone.extend(["--branch", info["ref"]])
        clone.extend([info["repo"], tmp_dir])
        commands.append(clone)
        commands.append(["docker", "build", "-t", img, tmp_dir])

    return commands


def get_push_commands(info: dict, project_id: str) -> list:
    """Get push commands as list of command arrays."""
    img = f"gcr.io/{project_id}/{info['image']}:latest"
    return [["docker", "push", img]]


def get_cleanup_commands(info: dict, tmp_dir: str) -> list:
    """Get cleanup commands for external images."""
    if not is_internal(info):
        return [["rm", "-rf", tmp_dir]]
    return []


def execute_commands(commands: list, cwd=None):
    """Execute a list of command arrays."""
    for cmd in commands:
        run_cmd(cmd, cwd=cwd)


def print_commands(commands: list):
    """Print commands as manual steps."""
    for cmd in commands:
        print(" ".join(cmd))


# --- CLI Commands ---

def cmd_list(args):
    """List all images with their status."""
    settings = load_settings()
    project_id = args.project or settings.get("project_id")
    images = load_images_config()

    if not project_id:
        error("project_id not set. Run: ./cloud init")
        sys.exit(1)

    print(f"Images for project: {project_id}\n")

    # Gather data first to calculate column widths
    rows = []
    for name, info in images.items():
        image_name = info["image"]
        img_type = "internal" if is_internal(info) else "external"
        image_tag = f"gcr.io/{project_id}/{image_name}:latest"

        # Check local
        local_info = get_local_image_info(image_tag)
        if local_info:
            created = local_info.get("CreatedAt", "")[:10]  # Just date
            local_str = f"built {created}"
        else:
            local_str = "not built"

        # Check GCR
        gcr_info = get_gcr_image_info(project_id, image_name)
        if gcr_info:
            digest = gcr_info.get("image_summary", {}).get("digest", "")
            if digest:
                digest_short = digest.split(":")[-1][:8]
                gcr_str = f"exists ({digest_short})"
            else:
                gcr_str = "exists"
        else:
            gcr_str = "missing"

        rows.append((name, local_str, gcr_str, img_type))

    # Calculate column widths
    headers = ("Name", "Local", "GCR", "Type")
    widths = [max(len(h), max(len(r[i]) for r in rows)) + 2
              for i, h in enumerate(headers)]

    # Print header
    header_line = "".join(h.ljust(w) for h, w in zip(headers, widths))
    print(header_line)
    print("-" * len(header_line))

    # Print rows
    for row in rows:
        print("".join(str(c).ljust(w) for c, w in zip(row, widths)))


def get_image_or_exit(args, images: dict) -> tuple:
    """Validate image name and return (name, info) or exit."""
    if not args.name:
        error("Image name required. Options: " + ", ".join(images.keys()))
        sys.exit(1)

    if args.name not in images:
        error(f"Unknown image '{args.name}'. Options: " + ", ".join(images.keys()))
        sys.exit(1)

    return args.name, images[args.name]


def get_project_or_exit(args) -> str:
    """Get project ID from args or settings, exit if not set."""
    settings = load_settings()
    project_id = args.project or settings.get("project_id")

    if not project_id:
        error("project_id not set. Run: ./cloud init")
        sys.exit(1)

    return project_id


def cmd_build(args):
    """Build a specific Docker image."""
    images = load_images_config()
    name, info = get_image_or_exit(args, images)
    project_id = get_project_or_exit(args)

    tmp_dir = tempfile.mkdtemp(prefix="cloud-build-")
    try:
        commands = get_build_commands(info, project_id, tmp_dir)
        cwd = REPO_ROOT if is_internal(info) else None

        print(f"Building {info['image']}...")
        execute_commands(commands, cwd=cwd)
        success(f"Built: gcr.io/{project_id}/{info['image']}:latest")
    finally:
        # Clean up tmp dir if external
        if not is_internal(info) and Path(tmp_dir).exists():
            shutil.rmtree(tmp_dir)


def cmd_push(args):
    """Push a specific Docker image to GCR."""
    images = load_images_config()
    name, info = get_image_or_exit(args, images)
    project_id = get_project_or_exit(args)

    img = f"gcr.io/{project_id}/{info['image']}:latest"
    print(f"Pushing {img}...")
    execute_commands(get_push_commands(info, project_id))
    success(f"Pushed: {img}")


def deploy_single_image(name: str, info: dict, project_id: str, dry_run: bool) -> bool:
    """Deploy a single image. Returns True if deployed, False if skipped."""
    tmp_dir = f"/tmp/cloud-build-{name}"

    # Gather all commands
    commands = []
    commands.extend(get_build_commands(info, project_id, tmp_dir))
    commands.extend(get_push_commands(info, project_id))
    commands.extend(get_cleanup_commands(info, tmp_dir))

    if dry_run:
        print(f"# Manual steps to deploy {name}:")
        print_commands(commands)
        return True

    # Execute
    img = f"gcr.io/{project_id}/{info['image']}:latest"
    print(f"Deploying {name}...")

    try:
        cwd = REPO_ROOT if is_internal(info) else None
        build_cmds = get_build_commands(info, project_id, tmp_dir)
        execute_commands(build_cmds, cwd=cwd)

        push_cmds = get_push_commands(info, project_id)
        execute_commands(push_cmds)

        success(f"Deployed: {img}")
        return True
    finally:
        # Clean up tmp dir if external
        if not is_internal(info) and Path(tmp_dir).exists():
            shutil.rmtree(tmp_dir)


def cmd_deploy(args):
    """Build and push Docker image(s). Supports 'all' and --if-missing."""
    images = load_images_config()
    project_id = get_project_or_exit(args)

    if not args.name:
        error("Image name required. Options: " + ", ".join(images.keys()) + ", all")
        sys.exit(1)

    # Determine which images to deploy
    if args.name == "all":
        targets = list(images.items())
    elif args.name in images:
        targets = [(args.name, images[args.name])]
    else:
        error(f"Unknown image '{args.name}'. Options: " + ", ".join(images.keys()) + ", all")
        sys.exit(1)

    # Filter by --if-missing
    if args.if_missing:
        filtered = []
        for name, info in targets:
            image_name = info["image"]
            if not get_gcr_image_info(project_id, image_name):
                filtered.append((name, info))
            else:
                warn(f"Skipping {name}: already exists in GCR")
        targets = filtered

    if not targets:
        print("Nothing to deploy.")
        return

    # Deploy each target
    for name, info in targets:
        deploy_single_image(name, info, project_id, args.dry_run)


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

    # deploy (build + push)
    deploy_parser = subparsers.add_parser("deploy", help="Build and push image(s)")
    deploy_parser.add_argument("name", nargs="?", help=f"Image name: {image_names}, all")
    deploy_parser.add_argument("--project", help="GCP Project ID (overrides config)")
    deploy_parser.add_argument("--if-missing", action="store_true",
                               help="Only deploy images not already in GCR")
    deploy_parser.add_argument("--dry-run", action="store_true",
                               help="Show manual steps without executing")

    parsed = parser.parse_args(args)

    if not parsed.action:
        parser.print_help()
        sys.exit(1)

    actions = {
        "list": cmd_list,
        "build": cmd_build,
        "push": cmd_push,
        "deploy": cmd_deploy,
    }
    actions[parsed.action](parsed)


if __name__ == "__main__":
    main()

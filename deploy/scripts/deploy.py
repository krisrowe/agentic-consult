#!/usr/bin/env python3
"""Deploy infrastructure via terraform.

Usage:
    ./cloud deploy                      # Deploy everything from HEAD
    ./cloud deploy --ref abc123         # Deploy everything from specific ref
    ./cloud deploy mcp                  # Deploy only MCP service
    ./cloud deploy mcp --ref abc123     # Deploy MCP from specific ref
    ./cloud deploy config               # Sync config files only (no image build)
"""
import argparse
import configparser
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Resolve paths
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent.parent
TERRAFORM_DIR = REPO_ROOT / "deploy" / "terraform"
IMAGES_INI = REPO_ROOT / "deploy" / "images.ini"

sys.path.insert(0, str(REPO_ROOT))
from agentic_consult.paths import load_settings

# Component to terraform resource mapping
COMPONENT_TARGETS = {
    "mcp": "google_cloud_run_v2_service.mcp_service",
    "analyzer": "google_cloud_run_v2_job.analyzer_job",
    "fetcher": "google_cloud_run_v2_job.fetcher_job",
    "config": "google_storage_bucket_object.app_resource",
}

# Components that use image_tag (internal images from this repo)
INTERNAL_COMPONENTS = {"mcp", "analyzer"}

# Components that use fetcher_tag (external images)
EXTERNAL_COMPONENTS = {"fetcher"}


def run_cmd(cmd: list, cwd=None, capture=False, check=True) -> subprocess.CompletedProcess:
    """Run a shell command."""
    print(f"→ {' '.join(cmd)}", file=sys.stderr)
    if capture:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    else:
        result = subprocess.run(cmd, cwd=cwd)
    if check and result.returncode != 0:
        if capture:
            print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)
    return result


def get_head_sha() -> str:
    """Get current HEAD SHA."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()[:12]  # Short SHA


def git_status_clean() -> bool:
    """Check if working tree is clean (no uncommitted or untracked files)."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT, capture_output=True, text=True
    )
    return result.returncode == 0 and not result.stdout.strip()


def git_has_unpushed() -> bool:
    """Check if HEAD has commits not pushed to remote."""
    result = subprocess.run(
        ["git", "log", "@{u}..HEAD", "--oneline"],
        cwd=REPO_ROOT, capture_output=True, text=True
    )
    # If no upstream or has unpushed commits
    return result.returncode != 0 or bool(result.stdout.strip())


def load_images_config(ref: str = None) -> dict:
    """Load image definitions from deploy/images.ini, optionally at specific ref."""
    if ref is None:
        # Read from working directory
        parser = configparser.ConfigParser()
        parser.read(IMAGES_INI)
    else:
        # Read from git at specific ref
        result = subprocess.run(
            ["git", "show", f"{ref}:deploy/images.ini"],
            cwd=REPO_ROOT, capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"Error: Could not read images.ini at ref {ref}", file=sys.stderr)
            sys.exit(1)
        parser = configparser.ConfigParser()
        parser.read_string(result.stdout)

    images = {}
    for section in parser.sections():
        images[section] = dict(parser[section])
    return images


def gcr_image_exists(project_id: str, image_name: str, tag: str) -> bool:
    """Check if image:tag exists in GCR."""
    result = subprocess.run(
        ["gcloud", "container", "images", "list-tags",
         f"gcr.io/{project_id}/{image_name}",
         f"--filter=tags:{tag}", "--format=value(tags)"],
        capture_output=True, text=True
    )
    return tag in result.stdout


def build_and_push_internal(project_id: str, image_name: str, tag: str, ref: str, target: str):
    """Build internal image from git ref and push to GCR."""
    image_full = f"gcr.io/{project_id}/{image_name}:{tag}"

    with tempfile.TemporaryDirectory(prefix="deploy-build-") as tmp_dir:
        # Extract ref to temp dir
        print(f"  Extracting {ref} to temp dir...", file=sys.stderr)
        archive_cmd = f"git archive --format=tar {ref} | tar -x -C {tmp_dir}"
        subprocess.run(archive_cmd, shell=True, cwd=REPO_ROOT, check=True)

        # Build
        print(f"  Building {image_full}...", file=sys.stderr)
        run_cmd(["docker", "build", "--target", target, "-t", image_full, tmp_dir])

        # Push
        print(f"  Pushing {image_full}...", file=sys.stderr)
        run_cmd(["docker", "push", image_full])


def build_and_push_external(project_id: str, image_name: str, tag: str, repo_url: str):
    """Build external image from cloned repo and push to GCR."""
    image_full = f"gcr.io/{project_id}/{image_name}:{tag}"

    with tempfile.TemporaryDirectory(prefix="deploy-build-") as tmp_dir:
        # Clone external repo at ref
        print(f"  Cloning {repo_url} at {tag}...", file=sys.stderr)
        run_cmd(["git", "clone", "--depth", "1", "--branch", tag, repo_url, tmp_dir])

        # Build
        print(f"  Building {image_full}...", file=sys.stderr)
        run_cmd(["docker", "build", "-t", image_full, tmp_dir])

        # Push
        print(f"  Pushing {image_full}...", file=sys.stderr)
        run_cmd(["docker", "push", image_full])


def run_terraform(
    project_id: str,
    bucket_name: str,
    image_tag: str,
    fetcher_tag: str,
    target: str = None,
    plan_only: bool = False,
    dry_run: bool = False,
):
    """Run terraform init and apply/plan."""
    # Init (skip backend config for now since GCS backend is disabled)
    init_cmd = ["terraform", "init"]

    # Apply/plan command
    action = "plan" if plan_only else "apply"
    action_cmd = [
        "terraform", action,
        f"-var=project_id={project_id}",
        f"-var=bucket_name={bucket_name}",
        f"-var=image_tag={image_tag}",
        f"-var=fetcher_tag={fetcher_tag}",
    ]
    if not plan_only:
        action_cmd.insert(2, "-auto-approve")
    if target:
        action_cmd.append(f"-target={target}")

    if dry_run:
        print(f"# Would run in {TERRAFORM_DIR}:")
        print(" ".join(init_cmd))
        print(" ".join(action_cmd))
        return

    run_cmd(init_cmd, cwd=TERRAFORM_DIR)
    run_cmd(action_cmd, cwd=TERRAFORM_DIR)


def main():
    parser = argparse.ArgumentParser(
        description="Deploy infrastructure via terraform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ./cloud deploy                    Deploy everything from HEAD
  ./cloud deploy --ref v1.0.0       Deploy everything from tag v1.0.0
  ./cloud deploy mcp                Deploy only MCP from HEAD
  ./cloud deploy mcp --ref abc123   Deploy only MCP from ref abc123
  ./cloud deploy config             Sync config files only
""")
    parser.add_argument(
        "component", nargs="?",
        choices=list(COMPONENT_TARGETS.keys()),
        help="Component to deploy (default: all)"
    )
    parser.add_argument(
        "--ref",
        help="Git ref to deploy (default: HEAD SHA)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be done without doing it"
    )
    parser.add_argument(
        "--plan", action="store_true",
        help="Run terraform plan instead of apply"
    )
    args = parser.parse_args()

    # Git status checks
    if not args.ref:
        if not git_status_clean():
            print("Error: Working tree has uncommitted changes.", file=sys.stderr)
            print("Either:", file=sys.stderr)
            print("  1. Commit your changes first", file=sys.stderr)
            print("  2. Run with --ref HEAD to deploy current HEAD anyway", file=sys.stderr)
            sys.exit(1)
        print(f"Deploying from HEAD (working tree clean)", file=sys.stderr)

    # Warn about unpushed commits
    if git_has_unpushed():
        print("Warning: HEAD has unpushed commits. Proceeding anyway.", file=sys.stderr)

    # Load settings
    settings = load_settings()
    project_id = settings.get("project_id")
    bucket_name = settings.get("bucket_name")

    if not project_id or not bucket_name:
        print("Error: project_id and bucket_name must be set. Run ./cloud init first.", file=sys.stderr)
        sys.exit(1)

    # Determine image_tag
    if args.ref:
        image_tag = args.ref
    else:
        image_tag = get_head_sha()
    print(f"Image tag: {image_tag}", file=sys.stderr)

    # Load images config (at the ref if specified, else HEAD)
    images_config = load_images_config(args.ref)
    fetcher_config = images_config.get("fetcher", {})
    fetcher_tag = fetcher_config.get("ref", "latest")
    print(f"Fetcher tag: {fetcher_tag}", file=sys.stderr)

    # Determine which components to deploy
    if args.component:
        components = [args.component]
    else:
        components = ["analyzer", "mcp", "fetcher"]  # All image components

    # Config-only deploy: skip image building
    if args.component == "config":
        print("\nSyncing config files only (no image build)...", file=sys.stderr)
        run_terraform(
            project_id, bucket_name, image_tag, fetcher_tag,
            target=COMPONENT_TARGETS["config"],
            plan_only=args.plan,
            dry_run=args.dry_run
        )
        print("\n✓ Config sync complete" if not args.dry_run else "")
        return

    # Check GCR and build/push if needed
    for component in components:
        if component == "config":
            continue

        info = images_config.get(component, {})
        image_name = info.get("image")
        if not image_name:
            print(f"Warning: No image config for {component}, skipping", file=sys.stderr)
            continue

        # Determine tag for this component
        if component in INTERNAL_COMPONENTS:
            tag = image_tag
        else:
            tag = fetcher_tag

        print(f"\n[{component}] Checking gcr.io/{project_id}/{image_name}:{tag}...", file=sys.stderr)

        if gcr_image_exists(project_id, image_name, tag):
            print(f"  Already in GCR, skipping build", file=sys.stderr)
        elif args.dry_run:
            print(f"  Would build and push", file=sys.stderr)
        else:
            # Build and push
            if component in INTERNAL_COMPONENTS:
                target = info.get("target")
                build_and_push_internal(project_id, image_name, tag, args.ref or "HEAD", target)
            else:
                repo_url = info.get("repo")
                build_and_push_external(project_id, image_name, tag, repo_url)

    # Run terraform
    print("\n[terraform]", file=sys.stderr)
    target = COMPONENT_TARGETS.get(args.component) if args.component else None
    run_terraform(
        project_id, bucket_name, image_tag, fetcher_tag,
        target=target,
        plan_only=args.plan,
        dry_run=args.dry_run
    )

    if not args.dry_run:
        print(f"\n✓ {'Plan' if args.plan else 'Deployment'} complete")


if __name__ == "__main__":
    main()

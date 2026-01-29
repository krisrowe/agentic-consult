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
COMPONENTS_INI = REPO_ROOT / "deploy" / "components.ini"

sys.path.insert(0, str(REPO_ROOT))
from agentic_consult.paths import load_settings


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


def load_components_config(ref: str = None) -> dict:
    """Load component definitions from deploy/components.ini, optionally at specific ref."""
    if ref is None:
        # Read from working directory
        parser = configparser.ConfigParser()
        parser.read(COMPONENTS_INI)
    else:
        # Read from git at specific ref
        result = subprocess.run(
            ["git", "show", f"{ref}:deploy/components.ini"],
            cwd=REPO_ROOT, capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"Error: Could not read components.ini at ref {ref}", file=sys.stderr)
            sys.exit(1)
        parser = configparser.ConfigParser()
        parser.read_string(result.stdout)

    images = {}
    for section in parser.sections():
        images[section] = dict(parser[section])
    return images


def check_docker_available() -> bool:
    """Check if docker CLI is available."""
    return shutil.which("docker") is not None


def get_image_url(project_id: str, image_name: str, tag: str, registry: str = None) -> str:
    """Construct full image URL.
    
    If registry is provided, use it.
    If image_name looks like a full URL (has domain), use it.
    Otherwise default to gcr.io/project_id/image_name.
    """
    if "/" in image_name and "." in image_name.split("/")[0]:
        # Fully qualified (e.g. ghcr.io/user/repo)
        return f"{image_name}:{tag}"
    
    base = registry or f"gcr.io/{project_id}"
    return f"{base}/{image_name}:{tag}"


def gcr_image_exists(image_url: str) -> bool:
    """Check if image exists in GCR using gcloud.
    
    Only works for gcr.io or pkg.dev images in the current project.
    Returns False for external registries (like GHCR) unless we add specific logic.
    """
    if "gcr.io" not in image_url and "pkg.dev" not in image_url:
        # Fallback: Assume external images exist if we can't check them easily via gcloud
        return False

    # Extract repo and tag
    # URL: gcr.io/proj/img:tag
    try:
        repo, tag = image_url.rsplit(":", 1)
        result = subprocess.run(
            ["gcloud", "container", "images", "list-tags",
             repo, f"--filter=tags:{tag}", "--format=value(tags)"],
            capture_output=True, text=True
        )
        return tag in result.stdout
    except Exception:
        return False


def build_and_push_internal(image_full: str, ref: str, target: str):
    """Build internal image from git ref and push."""
    if not check_docker_available():
        print(f"  Warning: Docker not found. Skipping build for {image_full}.", file=sys.stderr)
        print(f"  Assuming image is built remotely (e.g. GitHub Actions).", file=sys.stderr)
        return

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


def build_and_push_external(image_full: str, tag: str, repo_url: str):
    """Build external image from cloned repo and push."""
    if not check_docker_available():
        print(f"  Warning: Docker not found. Skipping build for {image_full}.", file=sys.stderr)
        return

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
    mcp_image: str,
    fetcher_image: str,
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
        f"-var=mcp_image={mcp_image}",
        f"-var=fetcher_image={fetcher_image}",
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
    # Load components config to get valid choices
    components_config = load_components_config()
    component_targets = {name: cfg.get("terraform") for name, cfg in components_config.items() if cfg.get("terraform")}

    parser.add_argument(
        "component", nargs="?",
        choices=list(component_targets.keys()),
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

    # Reload config at the specified ref (may differ from HEAD)
    if args.ref:
        components_config = load_components_config(args.ref)
        component_targets = {name: cfg.get("terraform") for name, cfg in components_config.items() if cfg.get("terraform")}

    # Derive component categories from config
    # - image_components: have 'image' field (need building)
    # - internal: have 'image' but no 'repo' (use image_tag from this repo)
    # - external: have 'image' and 'repo' (use ref from config)
    image_components = [name for name, cfg in components_config.items() if cfg.get("image")]
    internal_components = {name for name, cfg in components_config.items() if cfg.get("image") and not cfg.get("repo")}
    external_components = {name for name, cfg in components_config.items() if cfg.get("image") and cfg.get("repo")}

    fetcher_config = components_config.get("fetcher", {})
    fetcher_tag = fetcher_config.get("ref", "latest")
    print(f"Fetcher tag: {fetcher_tag}", file=sys.stderr)

    # Determine which components to deploy
    if args.component:
        components = [args.component]
    else:
        components = image_components  # All image components

    # Config-only deploy: skip image building
    if args.component == "config":
        print("\nSyncing config files only (no image build)...", file=sys.stderr)
        run_terraform(
            project_id, bucket_name, image_tag, fetcher_tag,
            target=component_targets["config"],
            plan_only=args.plan,
            dry_run=args.dry_run
        )
        print("\n✓ Config sync complete" if not args.dry_run else "")
        return

    # Check GCR and build/push if needed
    for component in components:
        if component == "config":
            continue

        info = components_config.get(component, {})
        image_name = info.get("image")
        registry = info.get("registry")
        
        if not image_name:
            print(f"Warning: No image config for {component}, skipping", file=sys.stderr)
            continue

        # Determine tag for this component
        if component in internal_components:
            tag = image_tag
        else:
            tag = fetcher_tag

        image_full = get_image_url(project_id, image_name, tag, registry)
        print(f"\n[{component}] Checking {image_full}...", file=sys.stderr)

        if gcr_image_exists(image_full):
            print(f"  Already in GCR, skipping build", file=sys.stderr)
        elif args.dry_run:
            print(f"  Would build and push", file=sys.stderr)
        else:
            # Build and push
            if component in internal_components:
                target = info.get("target")
                build_and_push_internal(project_id, image_name, tag, args.ref or "HEAD", target)
            else:
                repo_url = info.get("repo")
                build_and_push_external(project_id, image_name, tag, repo_url)

    # Run terraform
    print("\n[terraform]", file=sys.stderr)
    target = component_targets.get(args.component) if args.component else None

    # Resolve full image URLs for terraform variables
    mcp_info = components_config.get("mcp", {})
    mcp_url = get_image_url(
        project_id, 
        mcp_info.get("image", "consult-mcp"), 
        image_tag, 
        mcp_info.get("registry")
    )

    fetcher_info = components_config.get("fetcher", {})
    fetcher_url = get_image_url(
        project_id, 
        fetcher_info.get("image", "gmex-fetcher"), 
        fetcher_tag, 
        fetcher_info.get("registry")
    )

    run_terraform(
        project_id, bucket_name, mcp_url, fetcher_url,
        target=target,
        plan_only=args.plan,
        dry_run=args.dry_run
    )

    if not args.dry_run:
        print(f"\n✓ {'Plan' if args.plan else 'Deployment'} complete")


if __name__ == "__main__":
    main()

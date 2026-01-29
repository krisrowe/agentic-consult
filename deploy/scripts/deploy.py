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
    return result.stdout.strip()


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
    """Check if docker CLI is available and connected to a daemon."""
    if shutil.which("docker") is None:
        return False
    try:
        # Check if daemon is reachable (suppress output)
        subprocess.run(
            ["docker", "info"], 
            capture_output=True, 
            check=True, 
            timeout=5
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


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


def main():
    parser = argparse.ArgumentParser(
        description="Deploy infrastructure via terraform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ./cloud deploy                    Deploy using remote images (default)
  ./cloud deploy --build            Build images locally before deploying
  ./cloud deploy mcp                Deploy only MCP
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
        "--build", action="store_true",
        help="Build images locally before deploying (requires Docker)"
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

    # Track resolved URLs for terraform
    resolved_urls = {}

    # Image processing loop
    for component in components:
        if component == "config":
            continue

        info = components_config.get(component, {})
        image_name = info.get("image")
        registry = info.get("registry")
        
        if not image_name:
            continue

        # Determine tag for this component
        tag = image_tag if component in internal_components else fetcher_tag
        image_full = get_image_url(project_id, image_name, tag, registry)

        if args.build:
            print(f"\n[{component}] Building {image_full} locally...", file=sys.stderr)
            if component in internal_components:
                target = info.get("target")
                build_and_push_internal(image_full, args.ref or "HEAD", target)
            else:
                repo_url = info.get("repo")
                build_and_push_external(image_full, tag, repo_url)
        else:
            print(f"[{component}] Using remote image: {image_full}", file=sys.stderr)

        resolved_urls[component] = image_full

    # Run terraform
    print("\n[terraform]", file=sys.stderr)
    target = component_targets.get(args.component) if args.component else None

    # Resolve full image URLs for terraform variables
    mcp_info = components_config.get("mcp", {})
    mcp_url = resolved_urls.get("mcp", get_image_url(project_id, mcp_info.get("image", "consult-mcp"), image_tag, mcp_info.get("registry")))

    fetcher_info = components_config.get("fetcher", {})
    fetcher_url = resolved_urls.get("fetcher", get_image_url(project_id, fetcher_info.get("image", "gmex-fetcher"), fetcher_tag, fetcher_info.get("registry")))

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

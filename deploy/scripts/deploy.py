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
import os
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
    """Run a shell command, injecting SA credentials if available."""
    print(f"→ {' '.join(cmd)}", file=sys.stderr)
    
    # Inject Service Account credentials if configured
    env = os.environ.copy()
    settings = load_settings()
    sa_key_path = settings.get("cloud_deploy_service_account")
    
    if sa_key_path and os.path.exists(sa_key_path):
        # Terraform/Client libraries use this
        env["GOOGLE_APPLICATION_CREDENTIALS"] = sa_key_path
        # gcloud CLI uses this to override local user login
        env["CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE"] = sa_key_path

    if capture:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    else:
        result = subprocess.run(cmd, cwd=cwd, env=env)
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


def get_image_url(project_id: str, image_name: str, tag: str, registry: str = None) -> str:
    """Construct full image URL.
    
    If registry is provided, use it.
    If image_name looks like a full URL (has domain), use it.
    Otherwise default to gcr.io/project_id/image_name.
    """
    if "/" in image_name and "." in image_name.split("/"[0]):
        # Fully qualified (e.g. ghcr.io/user/repo)
        return f"{image_name}:{tag}"
    
    base = registry or f"gcr.io/{project_id}"
    return f"{base}/{image_name}:{tag}"


def check_gcr_image_exists(image_url: str) -> bool:
    """Check if image exists in GCR/Artifact Registry using gcloud."""
    if "gcr.io" not in image_url and "pkg.dev" not in image_url:
        return False
        
    print(f"  Checking GCR: {image_url}...", file=sys.stderr)
    try:
        subprocess.run(
            ["gcloud", "container", "images", "describe", image_url],
            capture_output=True, check=True
        )
        return True
    except subprocess.CalledProcessError:
        return False


def transfer_ghcr_to_gcr(project_id: str, src_image: str, dest_image: str):
    """Use Cloud Build to pull from GHCR and push to GCR."""
    print(f"  Transferring {src_image} -> {dest_image} via Cloud Build...", file=sys.stderr)
    
    sa_email = f"terraform-deployer@{project_id}.iam.gserviceaccount.com"
    
    config = f"""
steps:
- name: 'gcr.io/cloud-builders/docker'
  args: ['pull', '{src_image}']
- name: 'gcr.io/cloud-builders/docker'
  args: ['tag', '{src_image}', '{dest_image}']
- name: 'gcr.io/cloud-builders/docker'
  args: ['push', '{dest_image}']
images: ['{dest_image}']
"""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".yaml") as f:
        f.write(config)
        config_path = f.name

    try:
        cmd = [
            "gcloud", "builds", "submit",
            f"--project={project_id}",
            f"--config={config_path}",
            f"--service-account=projects/{project_id}/serviceAccounts/{sa_email}",
            "--logging=cloud-logging-only",
            "--no-source"
        ]
        run_cmd(cmd)
    finally:
        os.unlink(config_path)


def build_from_source_on_cloud(project_id: str, repo_url: str, ref: str, dest_image: str):
    """Use Cloud Build to build from a remote git repository."""
    print(f"  Building from {repo_url}@{ref} -> {dest_image} via Cloud Build...", file=sys.stderr)
    
    sa_email = f"terraform-deployer@{project_id}.iam.gserviceaccount.com"

    with tempfile.TemporaryDirectory(prefix="deploy-cloud-build-") as tmp_dir:
        print(f"  Cloning repo to {tmp_dir}...", file=sys.stderr)
        run_cmd(["git", "clone", "--depth", "1", "--branch", ref, repo_url, tmp_dir])
        
        cmd = [
            "gcloud", "builds", "submit",
            f"--project={project_id}",
            f"--tag={dest_image}",
            f"--service-account=projects/{project_id}/serviceAccounts/{sa_email}",
            "--logging=cloud-logging-only",
            tmp_dir
        ]
        run_cmd(cmd)


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
  ./cloud deploy                    Deploy using remote images (auto-transfer/build)
  ./cloud deploy mcp                Deploy only MCP
  ./cloud deploy config             Sync config files only
"""
    )
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

    # Reload config at the specified ref
    if args.ref:
        components_config = load_components_config(args.ref)
        component_targets = {name: cfg.get("terraform") for name, cfg in components_config.items() if cfg.get("terraform")}

    image_components = [name for name, cfg in components_config.items() if cfg.get("image")]
    internal_components = {name for name, cfg in components_config.items() if cfg.get("image") and not cfg.get("repo")}

    fetcher_config = components_config.get("fetcher", {})
    fetcher_tag = fetcher_config.get("ref", "latest")
    print(f"Fetcher tag: {fetcher_tag}", file=sys.stderr)

    if args.component:
        components = [args.component]
    else:
        components = image_components

    # Config-only deploy
    if args.component == "config":
        print("\nSyncing config files only (no image build)...", file=sys.stderr)
        mcp_info = components_config.get("mcp", {})
        mcp_url = get_image_url(project_id, mcp_info.get("image", "consult-mcp"), image_tag)
        fetcher_info = components_config.get("fetcher", {})
        fetcher_url = get_image_url(project_id, fetcher_info.get("image", "gmex-fetcher"), fetcher_tag)

        run_terraform(
            project_id, bucket_name, mcp_url, fetcher_url,
            target=component_targets["config"],
            plan_only=args.plan,
            dry_run=args.dry_run
        )
        return

    # Track final GCR URLs for terraform
    final_urls = {}

    # Image processing loop
    for component in components:
        if component == "config":
            continue

        info = components_config.get(component, {})
        image_name = info.get("image")
        if not image_name:
            continue

        # Target GCR Image
        tag = image_tag if component in internal_components else fetcher_tag
        target_gcr = get_image_url(project_id, image_name, tag)

        # Check if exists in GCR
        if check_gcr_image_exists(target_gcr):
            print(f"[{component}] Found in GCR: {target_gcr}", file=sys.stderr)
            final_urls[component] = target_gcr
            continue
        
        if args.dry_run:
            print(f"[{component}] Would transfer/build -> {target_gcr}", file=sys.stderr)
            final_urls[component] = target_gcr
            continue

        # Not found: Transfer or Build
        if component in internal_components:
            # Transfer from GHCR
            ghcr_registry = info.get("registry", "ghcr.io")
            ghcr_image = f"{ghcr_registry}/{image_name}"
            src_tag = f"sha-{tag}" if len(tag) >= 7 and not tag.startswith("sha-") else tag
            src_url = f"{ghcr_image}:{src_tag}"
            
            print(f"[{component}] Missing from GCR. Transferring from {src_url}...", file=sys.stderr)
            transfer_ghcr_to_gcr(project_id, src_url, target_gcr)
        else:
            # External: Build from source
            repo_url = info.get("repo")
            ref = info.get("ref", "master")
            print(f"[{component}] Missing from GCR. Building from {repo_url}...", file=sys.stderr)
            build_from_source_on_cloud(project_id, repo_url, ref, target_gcr)

        final_urls[component] = target_gcr

    # Run terraform
    print("\n[terraform]", file=sys.stderr)
    target = component_targets.get(args.component) if args.component else None

    mcp_info = components_config.get("mcp", {})
    mcp_default = get_image_url(project_id, mcp_info.get("image", "consult-mcp"), image_tag)
    mcp_url = final_urls.get("mcp", mcp_url if 'mcp_url' in locals() else mcp_default)

    fetcher_info = components_config.get("fetcher", {})
    fetcher_default = get_image_url(project_id, fetcher_info.get("image", "gmex-fetcher"), fetcher_tag)
    fetcher_url = final_urls.get("fetcher", fetcher_url if 'fetcher_url' in locals() else fetcher_default)

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

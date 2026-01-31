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
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
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


def get_git_repo_slug() -> str:
    """Get 'user/repo' from git remote origin."""
    try:
        res = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True
        )
        url = res.stdout.strip()
        if url.endswith(".git"):
            url = url[:-4]
        
        # Handle SSH: git@github.com:user/repo
        if "@" in url and ":" in url:
            return url.split(":")[-1]
            
        # Handle HTTPS: https://github.com/user/repo
        parts = url.split("/")
        if len(parts) >= 2:
            return f"{parts[-2]}/{parts[-1]}"
            
        return "unknown/unknown"
    except subprocess.CalledProcessError:
        return "unknown/unknown"


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
    if "/" in image_name and "." in image_name.split("/")[0]:
        # Fully qualified (e.g. ghcr.io/user/repo)
        return f"{image_name}:{tag}"
    
    base = registry or f"gcr.io/{project_id}"
    return f"{base}/{image_name}:{tag}"


def wait_for_gh_build(ref: str, timeout: int = 300) -> bool:
    """Check and wait for GitHub Actions build for the given ref."""
    if shutil.which("gh") is None:
        return False

    print(f"  Checking GitHub Actions for {ref}...", file=sys.stderr)
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            # List runs for this commit
            res = subprocess.run(
                ["gh", "run", "list", "--commit", ref, "--json", "status,conclusion,databaseId", "--limit", "1"],
                cwd=REPO_ROOT, capture_output=True, text=True
            )
            if res.returncode != 0:
                return False
                
            runs = json.loads(res.stdout)
            if not runs:
                # No run found yet - maybe just pushed? Wait a bit.
                if time.time() - start_time < 30: 
                    time.sleep(5)
                    continue
                return False # Give up if not found quickly

            run = runs[0]
            status = run.get("status")
            conclusion = run.get("conclusion")
            
            if status == "completed":
                if conclusion == "success":
                    print(f"  GitHub Build passed (Run {run.get('databaseId')}).", file=sys.stderr)
                    return True
                else:
                    print(f"  GitHub Build failed/cancelled ({conclusion}).", file=sys.stderr)
                    return False
            
            # Still running/queued
            print(f"  GitHub Build in progress ({status})... waiting...", end="\r", file=sys.stderr)
            time.sleep(10)
            
        except (json.JSONDecodeError, Exception) as e:
            pass

    print(f"\n  Timed out waiting for GitHub Build.", file=sys.stderr)
    return False


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
options:
  logging: CLOUD_LOGGING_ONLY
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
            "--no-source"
        ]
        run_cmd(cmd)
    finally:
        os.unlink(config_path)


def build_from_source_on_cloud(project_id: str, repo_url: str, ref: str, dest_image: str):
    """Use Cloud Build to build from a remote git repository."""
    print(f"  Building from {repo_url}@{ref} -> {dest_image} via Cloud Build...", file=sys.stderr)
    
    sa_email = f"terraform-deployer@{project_id}.iam.gserviceaccount.com"

    # Use a YAML config to specify logging and image tag
    config = f"""
steps:
- name: 'gcr.io/cloud-builders/docker'
  args: ['build', '-t', '{dest_image}', '.']
images: ['{dest_image}']
options:
  logging: CLOUD_LOGGING_ONLY
"""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".yaml") as f:
        f.write(config)
        config_path = f.name

    try:
        with tempfile.TemporaryDirectory(prefix="deploy-cloud-build-") as tmp_dir:
            print(f"  Cloning repo to {tmp_dir}...", file=sys.stderr)
            run_cmd(["git", "clone", "--depth", "1", "--branch", ref, repo_url, tmp_dir])
            
            cmd = [
                "gcloud", "builds", "submit",
                f"--project={project_id}",
                f"--config={config_path}",
                f"--service-account=projects/{project_id}/serviceAccounts/{sa_email}",
                tmp_dir
            ]
            run_cmd(cmd)
    finally:
        os.unlink(config_path)


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
    init_cmd = ["terraform", "init"]

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
            sys.exit(1)
        print(f"Deploying from HEAD (working tree clean)", file=sys.stderr)

    # Load settings
    settings = load_settings()
    project_id = settings.get("project_id")
    bucket_name = settings.get("bucket_name")

    if not project_id or not bucket_name:
        print("Error: project_id and bucket_name must be set. Run ./cloud init first.", file=sys.stderr)
        sys.exit(1)

    # Determine image_tag
    if args.ref:
        try:
            res = subprocess.run(
                ["git", "rev-parse", args.ref],
                cwd=REPO_ROOT, capture_output=True, text=True, check=True
            )
            image_tag = res.stdout.strip()
        except subprocess.CalledProcessError:
            image_tag = args.ref
    else:
        image_tag = get_head_sha()
    print(f"Image tag: {image_tag}", file=sys.stderr)

    # Reload config at the specified ref
    if args.ref:
        components_config = load_components_config(args.ref)
        component_targets = {name: cfg.get("terraform") for name, cfg in components_config.items() if cfg.get("terraform")}

    # Auto-detect image names
    git_slug = get_git_repo_slug()
    for name, cfg in components_config.items():
        if cfg.get("image") == "auto":
            if name == "mcp":
                cfg["image"] = f"{git_slug}-mcp"
            else:
                cfg["image"] = f"{git_slug}-{name}"

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
        mcp_url = get_image_url(project_id, mcp_info.get("image", "consult-mcp"), image_tag, mcp_info.get("registry"))
        fetcher_info = components_config.get("fetcher", {})
        fetcher_url = get_image_url(project_id, fetcher_info.get("image", "gmex-fetcher"), fetcher_tag, fetcher_info.get("registry"))

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

        tag = image_tag if component in internal_components else fetcher_tag
        target_gcr = get_image_url(project_id, image_name, tag)

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
            # Check GH Actions Status first
            if len(tag) >= 40: # Only wait for full SHAs
                 wait_for_gh_build(tag)

            ghcr_registry = info.get("registry", "ghcr.io")
            ghcr_image = f"{ghcr_registry}/{image_name}"
            src_tag = f"sha-{tag}" if len(tag) >= 7 and not tag.startswith("sha-") else tag
            src_url = f"{ghcr_image}:{src_tag}"
            
            print(f"[{component}] Missing from GCR. Transferring from {src_url}...", file=sys.stderr)
            transfer_ghcr_to_gcr(project_id, src_url, target_gcr)
        else:
            repo_url = info.get("repo")
            ref = info.get("ref", "master")
            print(f"[{component}] Missing from GCR. Building from {repo_url}...", file=sys.stderr)
            build_from_source_on_cloud(project_id, repo_url, ref, target_gcr)

        final_urls[component] = target_gcr

    # Run terraform
    print("\n[terraform]", file=sys.stderr)
    target = component_targets.get(args.component) if args.component else None

    mcp_info = components_config.get("mcp", {})
    mcp_default = get_image_url(project_id, mcp_info.get("image", "consult-mcp"), image_tag, mcp_info.get("registry"))
    mcp_url = final_urls.get("mcp", mcp_default)

    fetcher_info = components_config.get("fetcher", {})
    fetcher_default = get_image_url(project_id, fetcher_info.get("image", "gmex-fetcher"), fetcher_tag, fetcher_info.get("registry"))
    fetcher_url = final_urls.get("fetcher", fetcher_default)

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
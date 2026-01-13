"""CLI for cloud management and deployment."""

import click
import json
import subprocess
import sys
import os
from typing import Optional
from pathlib import Path
from ..config import load_main_config, set_app_config_value

def run_cmd(cmd, cwd=None, capture=False):
    """Run a shell command with consistent logging/error handling."""
    if not capture:
        print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    try:
        return subprocess.run(cmd, check=True, cwd=cwd, capture_output=capture, text=True)
    except subprocess.CalledProcessError as e:
        if not capture:
            click.secho(f"Error: Command failed with code {e.returncode}", fg="red", err=True)
        raise

def lookup_project_by_label(label_key: str = "agentic-consult", label_value: str = "default") -> str:
    """Discover GCP project via labels."""
    try:
        res = run_cmd([
            "gcloud", "projects", "list", f"--filter=labels.{label_key}={label_value}", "--format=value(projectId)"
        ], capture=True)
        ids = res.stdout.strip().splitlines()
        return ids[0] if ids else ""
    except:
        return ""

def lookup_bucket_by_label(project_id: str, label_key: str = "agentic-consult", label_value: str = "default") -> str:
    """Discover GCS bucket by label. Returns name or empty string."""
    try:
        res = run_cmd([
            "gcloud", "storage", "buckets", "list", 
            f"--project={project_id}", 
            f"--filter=labels.{label_key}={label_value}", 
            "--format=value(name)"
        ], capture=True)
        names = res.stdout.strip().splitlines()
        if len(names) > 1:
            click.secho(f"❌ Error: Multiple buckets found with label {label_key}={label_value}.", fg="red", err=True)
            sys.exit(1)
        return names[0] if names else ""
    except:
        return ""

def bucket_exists(project_id: str, bucket_name: str) -> bool:
    """Check if a bucket exists."""
    try:
        run_cmd(["gcloud", "storage", "buckets", "describe", f"gs://{bucket_name}", f"--project={project_id}"], capture=True)
        return True
    except:
        return False

def secret_exists(project_id: str, secret_id: str) -> bool:
    """Check if a secret exists in Secret Manager."""
    try:
        run_cmd([
            "gcloud", "secrets", "describe", secret_id, f"--project={project_id}"
        ], capture=True)
        return True
    except:
        return False

def get_secret_value(project_id: str, secret_id: str, version: str = "latest") -> Optional[str]:
    """Retrieve raw secret value from GCP Secret Manager."""
    try:
        res = run_cmd([
            "gcloud", "secrets", "versions", "access", version, f"--secret={secret_id}", f"--project={project_id}"
        ], capture=True)
        return res.stdout.strip()
    except:
        return None

@click.group()
def cloud():
    """Cloud deployment and management."""
    pass

@cloud.group(name="config")
def cloud_config():
    """Manage cloud coordinates and secrets."""
    pass

@cloud_config.command("secrets-list")
def cloud_config_secrets_list():
    """List metadata for required cloud secrets."""
    data = load_main_config()
    project_id = data.get("project_id")
    if not project_id:
        click.secho("Error: project_id not set.", fg="red")
        sys.exit(1)
    
    required = ["gemini-api-key", "gmail-token"]
    results = []
    
    import hashlib
    for sid in required:
        val = get_secret_value(project_id, sid)
        if val:
            results.append({
                "secret_id": sid,
                "status": "PRESENT",
                "length": len(val),
                "sha256": hashlib.sha256(val.encode() if isinstance(val, str) else val).hexdigest()
            })
        else:
            results.append({
                "secret_id": sid,
                "status": "MISSING"
            })
            
    click.echo(json.dumps(results, indent=2))

@cloud_config.command("init")
@click.option("--project", help="GCP Project ID.")
@click.option("--bucket", help="Target bucket name.")
@click.option("--gemini-api-key", help="Gemini API Key string.")
@click.option("--gmail-token-path", help="Path to gmail token.json file for upload.")
@click.option("--allow-create-bucket", is_flag=True, help="Permit bucket creation.")
@click.option("--allow-change-bucket", is_flag=True, help="Permit switching labels between buckets.")
@click.option("--non-interactive", is_flag=True, help="Fail instead of prompting.")
def cloud_init(project, bucket, gemini_api_key, gmail_token_path, allow_create_bucket, allow_change_bucket, non_interactive):
    """Transactional cloud environment setup with strict safety."""
    
    # --- PHASE 1: VERIFICATION (READ-ONLY) ---
    
    # 1. Resolve Project
    project_id = project or lookup_project_by_label()
    if not project_id:
        click.secho("❌ Error: Could not determine Project ID. Pass --project or label your project.", fg="red")
        sys.exit(1)
    
    # 2. Validate Gemini API Key
    api_key_value = gemini_api_key
    if not secret_exists(project_id, "gemini-api-key") and not api_key_value:
        if non_interactive:
            click.secho("❌ Error: 'gemini-api-key' secret missing and --non-interactive set.", fg="red")
            sys.exit(1)
        api_key_value = click.prompt("Required Secret 'gemini-api-key' is missing. Enter value", hide_input=True)

    # 3. Validate Gmail Token
    token_data = None
    if not secret_exists(project_id, "gmail-token") and not gmail_token_path:
        if non_interactive:
            click.secho("❌ Error: 'gmail-token' secret missing and --non-interactive set.", fg="red")
            sys.exit(1)
        gmail_token_path = click.prompt("Required Secret 'gmail-token' is missing. Enter path to token.json file")
    
    if gmail_token_path:
        path = Path(gmail_token_path).expanduser()
        if not path.exists():
            click.secho(f"❌ Error: Gmail token file not found at {path}", fg="red")
            sys.exit(1)
        token_data = path.read_bytes()

    # 4. Validate Bucket Logic
    labeled_bucket = lookup_bucket_by_label(project_id)
    target_bucket = bucket or labeled_bucket or f"consult-data-{project_id}"
    
    do_unlabel_old = False
    if labeled_bucket and bucket and labeled_bucket != bucket:
        if not allow_change_bucket:
            if non_interactive:
                click.secho(f"❌ Error: Bucket '{labeled_bucket}' is already active. Pass --allow-change-bucket.", fg="red")
                sys.exit(1)
            if not click.confirm(f"Bucket '{labeled_bucket}' is active. Switch label to '{bucket}'?"):
                click.echo("Aborted.")
                sys.exit(1)
        do_unlabel_old = True

    do_create_bucket = False
    if not bucket_exists(project_id, target_bucket):
        if not allow_create_bucket:
            if non_interactive:
                click.secho(f"❌ Error: Bucket '{target_bucket}' does not exist. Pass --allow-create-bucket.", fg="red")
                sys.exit(1)
            if not click.confirm(f"Bucket '{target_bucket}' does not exist. Create it?"):
                click.echo("Aborted.")
                sys.exit(1)
        do_create_bucket = True

    # --- PHASE 2: EXECUTION (WRITE-ONLY) ---
    click.echo(f"Applying changes to project: {project_id}...")

    # 1. Handle Bucket
    if do_unlabel_old:
        click.echo(f"Unlabeling {labeled_bucket}...")
        run_cmd(["gcloud", "storage", "buckets", "update", f"gs://{labeled_bucket}", "--remove-labels=agentic-consult"])

    if do_create_bucket:
        click.echo(f"Creating gs://{target_bucket}...")
        run_cmd(["gcloud", "storage", "buckets", "create", f"gs://{target_bucket}", f"--project={project_id}"])

    click.echo(f"Ensuring {target_bucket} is labeled...")
    run_cmd(["gcloud", "storage", "buckets", "update", f"gs://{target_bucket}", "--update-labels=agentic-consult=default"])

    # 2. Handle Secrets
    def sync_secret(secret_id, value):
        if not secret_exists(project_id, secret_id):
            click.echo(f"Creating secret '{secret_id}'...")
            subprocess.run(
                ["gcloud", "secrets", "create", secret_id, f"--project={project_id}", "--replication-policy=automatic", "--data-file=-"],
                input=value, check=True
            )
        else:
            click.echo(f"Updating secret '{secret_id}'...")
            subprocess.run(
                ["gcloud", "secrets", "versions", "add", secret_id, f"--project={project_id}", "--data-file=-"],
                input=value, check=True
            )

    if api_key_value:
        sync_secret("gemini-api-key", api_key_value.encode())
    if token_data:
        sync_secret("gmail-token", token_data)

    # 3. Save Context
    set_app_config_value("project_id", project_id)
    click.secho("✅ Cloud environment successfully initialized.", fg="green")

@cloud_config.command("resolve")
def cloud_resolve():
    """Resolve coordinates for Terraform (JSON)."""
    data = load_main_config()
    project_id = data.get("project_id")
    if not project_id:
        print(json.dumps({"project_id": "", "bucket_name": ""}))
        return
    bucket_name = lookup_bucket_by_label(project_id)
    print(json.dumps({"project_id": project_id, "bucket_name": bucket_name}))

@cloud.command("deploy")
def cloud_deploy():
    """Build, Push, and Apply Infrastructure."""
    data = load_main_config()
    project_id = data.get("project_id")
    if not project_id: 
        click.secho("Error: project_id not set. Run: consult cloud config init", fg="red")
        return

    image = f"gcr.io/{project_id}/consult-analyzer:latest"
    run_cmd(["docker", "build", "--target", "analyzer", "-t", image, "."])
    run_cmd(["docker", "push", image])

    tf_dir = Path(__file__).parent.parent.parent / "deploy" / "terraform"
    run_cmd(["terraform", "init"], cwd=tf_dir)
    run_cmd(["terraform", "apply", "-auto-approve"], cwd=tf_dir)
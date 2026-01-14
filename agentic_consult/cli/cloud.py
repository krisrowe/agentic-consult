"""CLI for cloud management and deployment."""

import click
import json
import subprocess
import sys
from typing import Optional
from pathlib import Path
from ..config import load_main_config, set_app_config_value
from ..cloud import get_cloud_provider


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

    provider = get_cloud_provider()
    required = ["gemini-api-key", "gmail-token"]
    results = []

    import hashlib
    for sid in required:
        val = provider.get_secret_value(project_id, sid)
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
@click.option("--skip-terraform", is_flag=True, help="Skip terraform validation.")
def cloud_init(project, bucket, gemini_api_key, gmail_token_path, allow_create_bucket, allow_change_bucket, non_interactive, skip_terraform):
    """Transactional cloud environment setup with strict safety."""

    provider = get_cloud_provider()

    # --- PHASE 1: VERIFICATION (READ-ONLY) ---

    # 1. Resolve Project
    project_id = project or provider.lookup_project_by_label("agentic-consult", "default")
    if not project_id:
        click.secho("❌ Error: Could not determine Project ID. Pass --project or label your project.", fg="red")
        sys.exit(1)

    # 2. Validate Gemini API Key
    api_key_value = gemini_api_key
    if not provider.secret_exists(project_id, "gemini-api-key") and not api_key_value:
        if non_interactive:
            click.secho("❌ Error: 'gemini-api-key' secret missing and --non-interactive set.", fg="red")
            sys.exit(1)
        api_key_value = click.prompt("Required Secret 'gemini-api-key' is missing. Enter value", hide_input=True)

    # 3. Validate Gmail Token
    token_data = None
    if not provider.secret_exists(project_id, "gmail-token") and not gmail_token_path:
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
    labeled_bucket = provider.lookup_bucket_by_label(project_id, "agentic-consult", "default")
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
    if not provider.bucket_exists(project_id, target_bucket):
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
        provider.remove_bucket_labels(labeled_bucket, ["agentic-consult"])

    if do_create_bucket:
        click.echo(f"Creating gs://{target_bucket}...")
        provider.create_bucket(project_id, target_bucket)

    click.echo(f"Ensuring {target_bucket} is labeled...")
    provider.update_bucket_labels(target_bucket, {"agentic-consult": "default"})

    # 2. Handle Secrets
    if api_key_value:
        if not provider.secret_exists(project_id, "gemini-api-key"):
            click.echo("Creating secret 'gemini-api-key'...")
            provider.create_secret(project_id, "gemini-api-key", api_key_value.encode())
        else:
            click.echo("Updating secret 'gemini-api-key'...")
            provider.add_secret_version(project_id, "gemini-api-key", api_key_value.encode())

    if token_data:
        if not provider.secret_exists(project_id, "gmail-token"):
            click.echo("Creating secret 'gmail-token'...")
            provider.create_secret(project_id, "gmail-token", token_data)
        else:
            click.echo("Updating secret 'gmail-token'...")
            provider.add_secret_version(project_id, "gmail-token", token_data)

    # 3. Save Context
    set_app_config_value("project_id", project_id)
    set_app_config_value("bucket_name", target_bucket)

    # 4. Validate Terraform Configuration
    if not skip_terraform:
        tf_dir = Path(__file__).parent.parent.parent / "deploy" / "terraform"
        click.echo("Validating terraform configuration...")
        try:
            subprocess.run(["terraform", "init", "-backend=false", "-input=false"], cwd=tf_dir, capture_output=True, check=True, text=True)
            subprocess.run(["terraform", "validate"], cwd=tf_dir, capture_output=True, check=True, text=True)
            click.echo("  ✓ Terraform configuration valid")
        except subprocess.CalledProcessError as e:
            click.secho(f"  ✗ Terraform validation failed: {e.stderr}", fg="red")
            sys.exit(1)

    click.secho("✅ Cloud environment successfully initialized.", fg="green")


# NOTE: Terraform resolution moved to agentic_consult/paths.py
# which can be run directly as: python3 agentic_consult/paths.py
# See deploy/DESIGN.md "paths.py Pattern" for rationale.


REQUIRED_IMAGES = ["gmex-fetcher", "consult-analyzer"]


@cloud.command("deploy")
@click.option("--skip-validation", is_flag=True, help="Skip image validation")
@click.option("--skip-config-check", is_flag=True, help="Skip config vs GCP label validation")
def cloud_deploy(skip_validation: bool, skip_config_check: bool):
    """Deploy infrastructure to GCP.

    Validates config matches GCP labels and required images exist before running terraform.
    """
    provider = get_cloud_provider()
    data = load_main_config()
    project_id = data.get("project_id")
    bucket_name = data.get("bucket_name")
    if not project_id:
        click.secho("Error: project_id not set. Run: consult cloud config init", fg="red")
        sys.exit(1)
    if not bucket_name:
        click.secho("Error: bucket_name not set. Run: consult cloud config init", fg="red")
        sys.exit(1)

    # Validate config matches GCP labels (detect stale config)
    if not skip_config_check:
        click.echo("Validating config against GCP labels...")
        labeled_bucket = provider.lookup_bucket_by_label(project_id, "agentic-consult", "default")
        if not labeled_bucket:
            click.secho(f"Error: No bucket found with agentic-consult label in project {project_id}.", fg="red")
            click.secho("Run: consult cloud config init", fg="yellow")
            sys.exit(1)
        if labeled_bucket != bucket_name:
            click.secho(f"Error: Config mismatch! Config has '{bucket_name}' but GCP label is on '{labeled_bucket}'.", fg="red")
            click.secho("Run: consult cloud config init --bucket=<correct-bucket>", fg="yellow")
            sys.exit(1)
        click.echo(f"  ✓ Config matches GCP labels (bucket: {bucket_name})")

    # Validate images exist
    if not skip_validation:
        click.echo("Checking required images...")
        missing = []
        for image_name in REQUIRED_IMAGES:
            if provider.image_exists(project_id, image_name):
                click.echo(f"  ✓ {image_name}")
            else:
                click.secho(f"  ✗ {image_name}", fg="red")
                missing.append(image_name)

        if missing:
            click.echo()
            click.secho("Missing images. Run:", fg="yellow")
            click.echo()
            cmds = []
            for name in missing:
                if name == "gmex-fetcher":
                    cmds.append(f"cd <gmail-extractor-repo> && make build && make push PROJECT={project_id}")
                else:
                    cmds.append(f"consult image build && consult image push {project_id}")
            click.echo("\n\n".join(cmds))
            click.echo()
            sys.exit(1)
        click.echo()

    # Run terraform
    tf_dir = Path(__file__).parent.parent.parent / "deploy" / "terraform"
    click.echo("Initializing terraform...")
    subprocess.run(["terraform", "init", "-input=false"], cwd=tf_dir, check=True)

    click.echo("Applying infrastructure...")
    subprocess.run(["terraform", "apply", "-auto-approve"], cwd=tf_dir, check=True)

    click.secho("✅ Deployment complete.", fg="green")


# --- Scheduler Management ---

SCHEDULER_JOBS = {
    "fetcher": "trigger-email-fetch",
    "analyzer": "trigger-email-analysis",
}


@cloud.group(name="scheduler")
def cloud_scheduler():
    """Manage Cloud Scheduler jobs."""
    pass


@cloud_scheduler.command("list")
def scheduler_list():
    """List all scheduler jobs and their current schedules."""
    provider = get_cloud_provider()
    data = load_main_config()
    project_id = data.get("project_id")
    if not project_id:
        click.secho("Error: project_id not set. Run: consult cloud config init", fg="red")
        sys.exit(1)

    click.echo(f"Scheduler jobs in project: {project_id}\n")
    for alias, job_name in SCHEDULER_JOBS.items():
        job = provider.get_scheduler_job(project_id, job_name)
        if job:
            schedule = job.get("schedule", "N/A")
            state = job.get("state", "UNKNOWN")
            click.echo(f"  {alias:12} {schedule:20} {state}")
        else:
            click.secho(f"  {alias:12} NOT FOUND", fg="yellow")


@cloud_scheduler.command("show")
@click.argument("job", type=click.Choice(list(SCHEDULER_JOBS.keys())))
def scheduler_show(job: str):
    """Show details for a specific scheduler job."""
    provider = get_cloud_provider()
    data = load_main_config()
    project_id = data.get("project_id")
    if not project_id:
        click.secho("Error: project_id not set.", fg="red")
        sys.exit(1)

    job_name = SCHEDULER_JOBS[job]
    job_data = provider.get_scheduler_job(project_id, job_name)
    if not job_data:
        click.secho(f"Job '{job}' not found.", fg="red")
        sys.exit(1)

    click.echo(f"Job:      {job} ({job_name})")
    click.echo(f"Schedule: {job_data.get('schedule', 'N/A')}")
    click.echo(f"Timezone: {job_data.get('timeZone', 'UTC')}")
    click.echo(f"State:    {job_data.get('state', 'UNKNOWN')}")


@cloud_scheduler.command("set")
@click.argument("job", type=click.Choice(list(SCHEDULER_JOBS.keys())))
@click.argument("value")
@click.option("--cron", is_flag=True, help="Interpret value as raw cron expression")
def scheduler_set(job: str, value: str, cron: bool):
    """Set schedule for a job.

    \b
    Examples:
      consult cloud scheduler set fetcher 15        # every 15 minutes
      consult cloud scheduler set fetcher 30        # every 30 minutes
      consult cloud scheduler set fetcher '*/5 * * * *' --cron  # raw cron
    """
    provider = get_cloud_provider()
    data = load_main_config()
    project_id = data.get("project_id")
    if not project_id:
        click.secho("Error: project_id not set.", fg="red")
        sys.exit(1)

    if cron:
        schedule = value
    else:
        # Interpret as minutes
        try:
            mins = int(value)
            if mins <= 0 or mins > 60:
                click.secho("Error: minutes must be between 1 and 60", fg="red")
                sys.exit(1)
            if 60 % mins == 0:
                # Clean division - use */N format
                schedule = f"*/{mins} * * * *"
            else:
                # Odd interval - just run at specific minutes
                minutes = list(range(0, 60, mins))
                schedule = f"{','.join(map(str, minutes))} * * * *"
        except ValueError:
            click.secho(f"Error: '{value}' is not a valid number. Use --cron for raw cron expressions.", fg="red")
            sys.exit(1)

    job_name = SCHEDULER_JOBS[job]
    click.echo(f"Setting {job} to: {schedule}")
    provider.update_scheduler_schedule(project_id, job_name, schedule)
    click.secho("✅ Done.", fg="green")


@cloud_scheduler.command("pause")
@click.argument("job", type=click.Choice(list(SCHEDULER_JOBS.keys())))
def scheduler_pause(job: str):
    """Pause a scheduler job."""
    provider = get_cloud_provider()
    data = load_main_config()
    project_id = data.get("project_id")
    if not project_id:
        click.secho("Error: project_id not set.", fg="red")
        sys.exit(1)

    job_name = SCHEDULER_JOBS[job]
    provider.pause_scheduler_job(project_id, job_name)
    click.secho(f"✅ {job_name} paused.", fg="green")


@cloud_scheduler.command("resume")
@click.argument("job", type=click.Choice(list(SCHEDULER_JOBS.keys())))
def scheduler_resume(job: str):
    """Resume a paused scheduler job."""
    provider = get_cloud_provider()
    data = load_main_config()
    project_id = data.get("project_id")
    if not project_id:
        click.secho("Error: project_id not set.", fg="red")
        sys.exit(1)

    job_name = SCHEDULER_JOBS[job]
    provider.resume_scheduler_job(project_id, job_name)
    click.secho(f"✅ {job_name} resumed.", fg="green")


@cloud_scheduler.command("run")
@click.argument("job", type=click.Choice(list(SCHEDULER_JOBS.keys())))
def scheduler_run(job: str):
    """Trigger a job to run immediately."""
    provider = get_cloud_provider()
    data = load_main_config()
    project_id = data.get("project_id")
    if not project_id:
        click.secho("Error: project_id not set.", fg="red")
        sys.exit(1)

    job_name = SCHEDULER_JOBS[job]
    provider.run_scheduler_job(project_id, job_name)
    click.secho(f"✅ {job_name} triggered.", fg="green")

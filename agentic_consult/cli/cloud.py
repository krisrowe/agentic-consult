"""CLI for cloud management and deployment."""

import click
import json
import subprocess
import sys
from typing import Optional
from pathlib import Path
from ..config import load_main_config, set_app_config_value
from ..cloud import get_cloud_provider, read_cloud_status, CloudStatus, pre_deploy
from ..paths import APP_SLUG


def format_cloud_status(status: CloudStatus, format: str = "table") -> str:
    """Format CloudStatus for display.

    Args:
        status: CloudStatus object from read_cloud_status()
        format: "table" for ASCII table, "json" for JSON output

    Returns:
        Formatted string
    """
    if format == "json":
        return json.dumps(status.to_dict(), indent=2)

    # ASCII table format
    lines = []
    lines.append("┌──────────────────┬──────────┬─────────┬─────────────────────────────────────────────┐")
    lines.append("│ Resource         │ Status   │ Changed │ Guidance                                    │")
    lines.append("├──────────────────┼──────────┼─────────┼─────────────────────────────────────────────┤")

    for r in status.resources:
        name = r.name[:16].ljust(16)
        if r.status in ("found", "exists", "enabled"):
            status_str = f"✓ {r.status}"[:8].ljust(8)
        elif r.status == "missing":
            status_str = f"✗ {r.status}"[:8].ljust(8)
        else:
            status_str = r.status[:8].ljust(8)

        changed = "yes" if r.changed else "no"
        if r.change_type:
            changed = r.change_type[:7]
        changed = changed.ljust(7)

        guidance = (r.guidance or "")[:43].ljust(43)
        lines.append(f"│ {name} │ {status_str} │ {changed} │ {guidance} │")

    lines.append("└──────────────────┴──────────┴─────────┴─────────────────────────────────────────────┘")

    # Summary
    if status.deploy_ready:
        lines.append("\nDeploy ready: Yes")
    else:
        missing = [r.name for r in status.resources if r.status == "missing"]
        lines.append(f"\nDeploy ready: No ({len(missing)} missing: {', '.join(missing)})")

    return "\n".join(lines)


@click.group()
def cloud():
    """Cloud deployment and management."""
    pass


@cloud.command("status")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table", help="Output format")
def cloud_status(output_format: str):
    """Show cloud environment status (read-only)."""
    provider = get_cloud_provider()
    data = load_main_config()
    project_id = data.get("project_id")
    bucket_name = data.get("bucket_name")

    if not project_id:
        click.secho("Error: project_id not set. Run: consult cloud init", fg="red")
        sys.exit(1)

    status = read_cloud_status(provider, project_id, bucket_name)
    status.config_saved = True  # We have config if we got here
    click.echo(format_cloud_status(status, output_format))


@cloud.command("init")
@click.option("--project", help="GCP Project ID.")
@click.option("--bucket", help="Target bucket name.")
@click.option("--gemini-api-key", help="Gemini API Key string.")
@click.option("--gmail-token-path", help="Path to gmail token.json file for upload.")
@click.option("--allow-create-bucket", is_flag=True, help="Permit bucket creation.")
@click.option("--allow-change-bucket", is_flag=True, help="Permit switching labels between buckets.")
@click.option("--non-interactive", is_flag=True, help="Fail instead of prompting.")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table", help="Output format")
def cloud_init(project, bucket, gemini_api_key, gmail_token_path, allow_create_bucket, allow_change_bucket, non_interactive, output_format):
    """Transactional cloud environment setup with strict safety."""

    provider = get_cloud_provider()
    existing_config = load_main_config()

    # --- PHASE 1: VERIFICATION (READ-ONLY) ---

    # 1. Resolve Project: --project flag > existing config > label discovery
    project_id = project or existing_config.get("project_id") or provider.lookup_project_by_label(APP_SLUG, "default")
    if not project_id:
        click.secho("❌ Error: Could not determine Project ID. Pass --project or label your project.", fg="red")
        sys.exit(1)

    # 2. Validate project exists (if from config, might be stale/inaccessible)
    if not project and existing_config.get("project_id") and not provider.project_exists(project_id):
        click.secho(f"❌ Error: Configured project '{project_id}' not found or not accessible.", fg="red")
        click.secho("Verify your access to this project, or use --project to specify a different one.", fg="yellow")
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
    labeled_bucket = provider.lookup_bucket_by_label(project_id, APP_SLUG, "default")
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
        provider.remove_bucket_labels(labeled_bucket, [APP_SLUG])

    if do_create_bucket:
        click.echo(f"Creating gs://{target_bucket}...")
        provider.create_bucket(project_id, target_bucket)

    click.echo(f"Ensuring {target_bucket} is labeled...")
    provider.update_bucket_labels(target_bucket, {APP_SLUG: "default"})

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

    click.secho("✅ Cloud environment initialized.\n", fg="green")

    # 4. Show status (read-only check of all resources)
    status = read_cloud_status(provider, project_id, target_bucket)
    status.config_saved = True
    click.echo(format_cloud_status(status, output_format))


# NOTE: Terraform resolution moved to agentic_consult/paths.py
# which can be run directly as: python3 agentic_consult/paths.py
# See deploy/DESIGN.md "paths.py Pattern" for rationale.


# Import from status module to avoid duplication
from ..cloud.status import REQUIRED_IMAGES


@cloud.command("pre-deploy")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", help="Output format")
def cloud_pre_deploy(output_format: str):
    """Check deploy readiness and output terraform commands.

    Checks cloud status and either:
    - Outputs terraform commands to run (if ready)
    - Outputs issues with guidance (if not ready)
    """
    provider = get_cloud_provider()
    data = load_main_config()
    project_id = data.get("project_id")
    bucket_name = data.get("bucket_name")

    if not project_id:
        click.secho("Error: project_id not set. Run: consult cloud init", fg="red")
        sys.exit(1)
    if not bucket_name:
        click.secho("Error: bucket_name not set. Run: consult cloud init", fg="red")
        sys.exit(1)

    result = pre_deploy(provider, project_id, bucket_name)

    if output_format == "json":
        click.echo(json.dumps(result.to_dict(), indent=2))
        if not result.ready:
            sys.exit(1)
        return

    # Text format
    click.echo(format_cloud_status(result.status, "table"))
    click.echo()

    if not result.ready:
        click.secho("Fix the issues above before deploying.", fg="yellow")
        sys.exit(1)

    # Ready - output copy/paste commands
    click.secho("Ready to deploy. Run:", fg="green")
    click.echo()
    for cmd in result.terraform_commands:
        click.echo(f"  {cmd}")
    click.echo()


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
        click.secho("Error: project_id not set. Run: consult cloud init", fg="red")
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

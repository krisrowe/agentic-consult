#!/usr/bin/env python3
"""
Manage Cloud Scheduler jobs. Stdlib only.

Usage:
    ./cloud scheduler list
    ./cloud scheduler show fetcher
    ./cloud scheduler set fetcher 15
    ./cloud scheduler set fetcher '*/5 * * * *' --cron
    ./cloud scheduler pause fetcher
    ./cloud scheduler resume fetcher
    ./cloud scheduler run fetcher
"""
import argparse
import sys

from _common import load_settings, get_cloud_provider, error, success


SCHEDULER_JOBS = {
    "fetcher": "trigger-email-fetch",
    "analyzer": "trigger-email-analysis",
}


def cmd_list(args, provider, project_id):
    """List all scheduler jobs."""
    print(f"Scheduler jobs in project: {project_id}\n")
    for alias, job_name in SCHEDULER_JOBS.items():
        job = provider.get_scheduler_job(project_id, job_name)
        if job:
            schedule = job.get("schedule", "N/A")
            state = job.get("state", "UNKNOWN")
            print(f"  {alias:12} {schedule:20} {state}")
        else:
            print(f"  {alias:12} NOT FOUND")


def cmd_show(args, provider, project_id):
    """Show details for a specific job."""
    job_name = SCHEDULER_JOBS[args.job]
    job_data = provider.get_scheduler_job(project_id, job_name)

    if not job_data:
        error(f"Job '{args.job}' not found.")
        sys.exit(1)

    print(f"Job:      {args.job} ({job_name})")
    print(f"Schedule: {job_data.get('schedule', 'N/A')}")
    print(f"Timezone: {job_data.get('timeZone', 'UTC')}")
    print(f"State:    {job_data.get('state', 'UNKNOWN')}")


def cmd_set(args, provider, project_id):
    """Set schedule for a job."""
    if args.cron:
        schedule = args.value
    else:
        try:
            mins = int(args.value)
            if mins <= 0 or mins > 60:
                error("minutes must be between 1 and 60")
                sys.exit(1)
            if 60 % mins == 0:
                schedule = f"*/{mins} * * * *"
            else:
                minutes = list(range(0, 60, mins))
                schedule = f"{','.join(map(str, minutes))} * * * *"
        except ValueError:
            error(f"'{args.value}' is not a valid number. Use --cron for raw cron expressions.")
            sys.exit(1)

    job_name = SCHEDULER_JOBS[args.job]
    print(f"Setting {args.job} to: {schedule}")
    provider.update_scheduler_schedule(project_id, job_name, schedule)
    success("Done.")


def cmd_pause(args, provider, project_id):
    """Pause a job."""
    job_name = SCHEDULER_JOBS[args.job]
    provider.pause_scheduler_job(project_id, job_name)
    success(f"{job_name} paused.")


def cmd_resume(args, provider, project_id):
    """Resume a job."""
    job_name = SCHEDULER_JOBS[args.job]
    provider.resume_scheduler_job(project_id, job_name)
    success(f"{job_name} resumed.")


def cmd_run(args, provider, project_id):
    """Run a job immediately."""
    job_name = SCHEDULER_JOBS[args.job]
    provider.run_scheduler_job(project_id, job_name)
    success(f"{job_name} triggered.")


def main(args=None):
    parser = argparse.ArgumentParser(description="Manage Cloud Scheduler jobs")
    subparsers = parser.add_subparsers(dest="action", help="Action to perform")

    # list
    subparsers.add_parser("list", help="List all scheduler jobs")

    # show
    show_parser = subparsers.add_parser("show", help="Show job details")
    show_parser.add_argument("job", choices=list(SCHEDULER_JOBS.keys()))

    # set
    set_parser = subparsers.add_parser(
        "set",
        help="Set job schedule",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ./cloud scheduler set fetcher 15              # every 15 minutes
  ./cloud scheduler set fetcher 30              # every 30 minutes
  ./cloud scheduler set fetcher '*/5 * * * *' --cron  # raw cron
        """
    )
    set_parser.add_argument("job", choices=list(SCHEDULER_JOBS.keys()))
    set_parser.add_argument("value", help="Minutes (e.g., 15) or cron expression with --cron")
    set_parser.add_argument("--cron", action="store_true", help="Interpret value as raw cron")

    # pause
    pause_parser = subparsers.add_parser("pause", help="Pause a job")
    pause_parser.add_argument("job", choices=list(SCHEDULER_JOBS.keys()))

    # resume
    resume_parser = subparsers.add_parser("resume", help="Resume a job")
    resume_parser.add_argument("job", choices=list(SCHEDULER_JOBS.keys()))

    # run
    run_parser = subparsers.add_parser("run", help="Run a job now")
    run_parser.add_argument("job", choices=list(SCHEDULER_JOBS.keys()))

    parsed = parser.parse_args(args)

    if not parsed.action:
        parser.print_help()
        sys.exit(1)

    # Load config
    settings = load_settings()
    project_id = settings.get("project_id")
    if not project_id:
        error("project_id not set. Run: ./cloud init --project=YOUR_PROJECT")
        sys.exit(1)

    provider = get_cloud_provider()

    # Dispatch
    actions = {
        "list": cmd_list,
        "show": cmd_show,
        "set": cmd_set,
        "pause": cmd_pause,
        "resume": cmd_resume,
        "run": cmd_run,
    }
    actions[parsed.action](parsed, provider, project_id)


if __name__ == "__main__":
    main()

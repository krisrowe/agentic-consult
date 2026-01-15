#!/usr/bin/env python3
"""Deploy infrastructure via terraform.

Usage:
    ./cloud deploy [--dry-run]
"""
import argparse
import subprocess
import sys
from pathlib import Path

# Resolve paths
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent.parent
TERRAFORM_DIR = REPO_ROOT / "deploy" / "terraform"

sys.path.insert(0, str(REPO_ROOT))
from agentic_consult.paths import load_settings


def get_terraform_commands(
    project_id: str,
    bucket_name: str,
    plan_only: bool = False,
    deletion_protection: bool = None,
) -> list:
    """Build list of terraform commands to run."""
    action = "plan" if plan_only else "apply"
    cmd = [
        "terraform", action,
        f"-var=project_id={project_id}",
        f"-var=bucket_name={bucket_name}",
    ]
    if not plan_only:
        cmd.insert(2, "-auto-approve")
    if deletion_protection is not None:
        cmd.append(f"-var=service_delete_protection={str(deletion_protection).lower()}")
    return [["terraform", "init"], cmd]


def parse_bool(value: str) -> bool:
    """Parse string to bool for argparse."""
    if value.lower() in ("true", "1", "yes"):
        return True
    elif value.lower() in ("false", "0", "no"):
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value: {value}")


def main():
    parser = argparse.ArgumentParser(description="Deploy infrastructure via terraform")
    parser.add_argument("--dry-run", action="store_true", help="Show commands without running")
    parser.add_argument("--plan", action="store_true", help="Run terraform plan instead of apply")
    parser.add_argument(
        "--service-delete-protection",
        type=parse_bool,
        default=None,
        metavar="BOOL",
        help="Enable/disable deletion protection for Cloud Run jobs (default: terraform default)",
    )
    args = parser.parse_args()

    # Load settings
    settings = load_settings()
    project_id = settings.get("project_id")
    bucket_name = settings.get("bucket_name")

    if not project_id or not bucket_name:
        print("Error: project_id and bucket_name must be set. Run ./cloud init first.", file=sys.stderr)
        sys.exit(1)

    commands = get_terraform_commands(
        project_id,
        bucket_name,
        plan_only=args.plan,
        deletion_protection=args.service_delete_protection,
    )

    if args.dry_run:
        print(f"# Would run in {TERRAFORM_DIR}:\n")
        for cmd in commands:
            print(" ".join(cmd))
        return

    # Run terraform commands
    for cmd in commands:
        print(f"\n→ {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=TERRAFORM_DIR)
        if result.returncode != 0:
            print(f"Error: command failed with exit code {result.returncode}", file=sys.stderr)
            sys.exit(result.returncode)

    if args.plan:
        print("\n✓ Plan complete")
    else:
        print("\n✓ Deployment complete")


if __name__ == "__main__":
    main()

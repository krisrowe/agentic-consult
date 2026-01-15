"""
Shared utilities for deploy scripts. Stdlib only.
"""
import json
import os
import sys
from pathlib import Path

# ============================================
# Path setup - add repo root for imports
# ============================================

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Now we can import from agentic_consult
from agentic_consult.cloud import get_cloud_provider, read_cloud_status
from agentic_consult.paths import get_settings_dir, get_settings_path, load_settings, APP_SLUG


# ============================================
# Config helpers
# ============================================

def save_setting(key: str, value: str) -> None:
    """Save a single setting to settings.json."""
    settings_dir = get_settings_dir()
    settings_dir.mkdir(parents=True, exist_ok=True)

    settings = load_settings()
    settings[key] = value

    get_settings_path().write_text(json.dumps(settings, indent=2))


def save_settings(updates: dict) -> None:
    """Save multiple settings at once."""
    settings_dir = get_settings_dir()
    settings_dir.mkdir(parents=True, exist_ok=True)

    settings = load_settings()
    settings.update(updates)

    get_settings_path().write_text(json.dumps(settings, indent=2))


# ============================================
# ANSI colors (simple)
# ============================================

class Color:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RESET = '\033[0m'


def red(text: str) -> str:
    return f"{Color.RED}{text}{Color.RESET}"


def green(text: str) -> str:
    return f"{Color.GREEN}{text}{Color.RESET}"


def yellow(text: str) -> str:
    return f"{Color.YELLOW}{text}{Color.RESET}"


def error(msg: str) -> None:
    """Print error to stderr."""
    print(red(f"Error: {msg}"), file=sys.stderr)


def success(msg: str) -> None:
    """Print success message."""
    print(green(msg))


def warn(msg: str) -> None:
    """Print warning."""
    print(yellow(msg))


# ============================================
# Interactive prompts
# ============================================

def prompt(message: str, hide_input: bool = False) -> str:
    """Prompt for input. Returns stripped string."""
    if hide_input:
        import getpass
        return getpass.getpass(f"{message}: ")
    return input(f"{message}: ").strip()


def confirm(message: str, default: bool = False) -> bool:
    """Ask yes/no question. Returns boolean."""
    suffix = "[Y/n]" if default else "[y/N]"
    response = input(f"{message} {suffix}: ").strip().lower()

    if not response:
        return default
    return response in ('y', 'yes')


# ============================================
# Table formatting
# ============================================

def format_status_table(status, show_changes: bool = False) -> str:
    """Format CloudStatus as ASCII table.

    Args:
        status: CloudStatus object
        show_changes: If True, include Changed column (for init output)
    """
    lines = []

    if show_changes:
        lines.append("+--------------------+-----------+---------+--------------------------------------------------+")
        lines.append("| Resource           | Status    | Changed | Guidance                                         |")
        lines.append("+--------------------+-----------+---------+--------------------------------------------------+")
    else:
        lines.append("+--------------------+-----------+--------------------------------------------------+")
        lines.append("| Resource           | Status    | Guidance                                         |")
        lines.append("+--------------------+-----------+--------------------------------------------------+")

    def render_resource(r):
        name = r.name[:18].ljust(18)
        if r.status in ("found", "exists", "enabled"):
            status_str = f"+ {r.status}"[:9].ljust(9)
        elif r.status == "missing":
            status_str = f"- {r.status}"[:9].ljust(9)
        else:
            status_str = r.status[:9].ljust(9)
        guidance = (r.guidance or "")[:48].ljust(48)

        if show_changes:
            changed = "yes" if r.changed else "no"
            if r.change_type:
                changed = r.change_type[:7]
            changed = changed.ljust(7)
            return f"| {name} | {status_str} | {changed} | {guidance} |"
        else:
            return f"| {name} | {status_str} | {guidance} |"

    # Render pre_deploy resources
    for r in status.pre_deploy:
        lines.append(render_resource(r))

    # Separator between pre_deploy and deploy
    if status.deploy:
        if show_changes:
            lines.append("+--------------------+-----------+---------+--------------------------------------------------+")
        else:
            lines.append("+--------------------+-----------+--------------------------------------------------+")

        # Render deploy resources
        for r in status.deploy:
            lines.append(render_resource(r))

    # Final border
    if show_changes:
        lines.append("+--------------------+-----------+---------+--------------------------------------------------+")
    else:
        lines.append("+--------------------+-----------+--------------------------------------------------+")

    # Show overall status
    if status.status == "deployed":
        lines.append(f"\nStatus: {green('Deployed')}")
    elif status.status == "deploy_ready":
        lines.append(f"\nStatus: {green('Deploy Ready')}")
    else:
        missing = [r.name for r in status.pre_deploy if r.status == "missing"]
        lines.append(f"\nStatus: {red('Not Deploy Ready')} ({len(missing)} missing)")

    # Show guidance summary if available
    if hasattr(status, 'guidance') and status.guidance:
        lines.append("\nNext steps:")
        for i, group in enumerate(status.guidance):
            if i > 0:
                lines.append("")  # Blank line between groups
            if group.heading:
                lines.append(f"  {group.heading}")
                for item in group.items:
                    lines.append(f"    {item}")
            else:
                for item in group.items:
                    lines.append(f"  {item}")

    return "\n".join(lines)

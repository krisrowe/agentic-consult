"""TickTick task fetching via ticktick CLI."""
import json
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List
import click


import os


def fetch_tasks(customer: Dict, project: str = 'Work', use_gemini: bool = False) -> List[Dict]:
    """
    Fetch open TickTick tasks for customer using ticktick CLI.
    
    Args:
        customer: Customer config dict
        project: TickTick project name
        use_gemini: Whether to fall back to Gemini settings if auth fails.
    
    Returns:
        List of task dicts
    """
    if not shutil.which("ticktick"):
        click.echo("Warning: 'ticktick' CLI not found. Skipping task fetch.", err=True)
        return []

    # Check status first
    env = os.environ.copy()
    is_authenticated = False
    try:
        status_proc = subprocess.run(["ticktick", "status", "--format", "json"], capture_output=True, text=True, check=True)
        status_data = json.loads(status_proc.stdout)
        is_authenticated = status_data.get("access_token", {}).get("found", False)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        # Fallback to text check if JSON fails (older version of ticktick-access)
        try:
            status_proc = subprocess.run(["ticktick", "status"], capture_output=True, text=True, check=True)
            is_authenticated = "Access token: Not found" not in status_proc.stdout
        except subprocess.CalledProcessError:
            is_authenticated = False

    # If not authenticated, try Gemini token if enabled
    if not is_authenticated and use_gemini:
        # We need to manually load the token from ~/.gemini/settings.json
        # because we cannot import ticktick.config here (optional dependency)
        gemini_settings = Path.home() / ".gemini" / "settings.json"
        token = None
        if gemini_settings.exists():
            try:
                with open(gemini_settings, 'r') as f:
                    settings = json.load(f)
                    token = settings.get("mcpServers", {}).get("ticktick", {}).get("env", {}).get("TICKTICK_ACCESS_TOKEN")
            except Exception:
                pass
        
        if token:
            click.echo("Injecting TickTick token from Gemini settings...", err=True)
            env["TICKTICK_ACCESS_TOKEN"] = token
        else:
             click.echo("Warning: TickTick unauthenticated and no token found in Gemini settings.", err=True)
             return []
    elif not is_authenticated:
        click.echo("Warning: TickTick unauthenticated. Run 'ticktick auth' or configure Gemini fallback.", err=True)
        return []

    try:
        # Run ticktick tasks list [project] --format json
        cmd = ["ticktick", "tasks", "list", project, "--format", "json"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
        tasks = json.loads(result.stdout)
        
        # Filter tasks by customer name or keywords if needed
        # For now, we return all tasks in the project as the LLM will filter them
        return tasks
    except subprocess.CalledProcessError as e:
        click.echo(f"Error calling ticktick: {e.stderr}", err=True)
        return []
    except json.JSONDecodeError:
        click.echo("Error decoding ticktick output", err=True)
        return []


def save_tasks_to_json(tasks: List[Dict], tasks_dir: Path) -> None:
    """
    Save tasks to JSON file.
    
    Args:
        tasks: List of task dicts
        tasks_dir: Directory to save tasks JSON
    """
    tasks_dir.mkdir(parents=True, exist_ok=True)
    
    tasks_file = tasks_dir / 'tasks.json'
    with open(tasks_file, 'w') as f:
        json.dump(tasks, f, indent=2)


def load_tasks_from_json(tasks_dir: Path) -> List[Dict]:
    """
    Load tasks from local JSON file.
    
    Args:
        tasks_dir: Directory containing tasks.json
        
    Returns:
        List of task dicts
    """
    tasks_file = tasks_dir / 'tasks.json'
    if not tasks_file.exists():
        return []
    
    try:
        with open(tasks_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        click.echo(f"Warning: Failed to load cached tasks: {e}", err=True)
        return []


def fetch_and_cache_tasks(customer: Dict, customer_dir: Path, project: str = 'Work', use_gemini: bool = False, use_mock_data: bool = False) -> (int, Dict):
    """
    Fetch TickTick tasks, compare with cache, and save locally.
    
    Args:
        customer: Customer config dict
        customer_dir: Customer's data directory
        project: TickTick project name
        use_gemini: Whether to fall back to Gemini settings if auth fails.
        use_mock_data: Whether to use mock-server-tasks.json if available
    
    Returns:
        A tuple containing:
        - Total number of tasks available.
        - A dict with stats: {'new': int, 'updated': int, 'unchanged': int}.
    """
    tasks_dir = customer_dir / 'tasks'
    stats = {'new': 0, 'updated': 0, 'unchanged': 0}
    
    # Check for mock data
    if use_mock_data:
        mock_file = customer_dir / 'mock-server-tasks.json'
        if mock_file.exists():
            click.echo(f"Using mock tasks from {mock_file}")
            try:
                with open(mock_file, 'r') as f:
                    tasks = json.load(f)
                save_tasks_to_json(tasks, tasks_dir)
                # In mock mode, we can't calculate stats, so we assume all are new
                stats['new'] = len(tasks)
                return len(tasks), stats
            except Exception as e:
                click.echo(f"Error reading mock tasks: {e}", err=True)
                return 0, stats
        else:
             click.echo(f"Warning: use_mock_data is true but {mock_file} not found.", err=True)

    # Load old tasks for comparison
    old_tasks_list = load_tasks_from_json(tasks_dir)
    old_tasks_map = {task['id']: task for task in old_tasks_list}

    # Fetch tasks
    click.echo(f"Fetching tasks from project '{project}'...", err=True)
    new_tasks = fetch_tasks(customer, project=project, use_gemini=use_gemini)
    
    if not new_tasks and old_tasks_list:
        click.echo(f"Task fetch failed. Using {len(old_tasks_list)} cached tasks for {customer.get('name')}.", err=True)
        return len(old_tasks_list), stats

    # Compare and calculate stats
    if not isinstance(new_tasks, list):
        click.echo(f"Warning: Expected a list of tasks but got {type(new_tasks)}. Treating as empty.", err=True)
        new_tasks = []

    new_tasks_map = {task['id']: task for task in new_tasks}
    for task_id, task in new_tasks_map.items():
        if task_id not in old_tasks_map:
            stats['new'] += 1
        elif task != old_tasks_map[task_id]:
            stats['updated'] += 1
        else:
            stats['unchanged'] += 1
            
    # Save tasks
    save_tasks_to_json(new_tasks, tasks_dir)
    
    return len(new_tasks), stats

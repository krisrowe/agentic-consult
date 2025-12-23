"""TickTick task fetching via ticktick CLI."""
import json
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List
import click


def fetch_tasks(customer: Dict, project: str = 'Work') -> List[Dict]:
    """
    Fetch open TickTick tasks for customer using ticktick CLI.
    
    Args:
        customer: Customer config dict
        project: TickTick project name
    
    Returns:
        List of task dicts
    """
    if not shutil.which("ticktick"):
        click.echo("Warning: 'ticktick' CLI not found. Skipping task fetch.", err=True)
        return []

    try:
        # Run ticktick tasks list [project] --format json
        cmd = ["ticktick", "tasks", "list", project, "--format", "json"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
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


def fetch_and_cache_tasks(customer: Dict, customer_dir: Path, project: str = 'Work') -> int:
    """
    Fetch TickTick tasks and cache them locally.
    
    Args:
        customer: Customer config dict
        customer_dir: Customer's data directory
        project: TickTick project name
    
    Returns:
        Number of tasks fetched
    """
    tasks_dir = customer_dir / 'tasks'
    
    # Fetch tasks
    tasks = fetch_tasks(customer, project=project)
    
    # Save tasks
    if tasks:
        save_tasks_to_json(tasks, tasks_dir)
    
    return len(tasks)

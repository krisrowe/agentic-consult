"""
This package manages the local-first task store (tasks.json) and provides task provider interfaces.
"""
import json
from pathlib import Path
from typing import List, Dict, Optional
import datetime

# --- Local Task Management --- #

def get_next_sequence_number(tasks: List[Dict]) -> int:
    """Finds the max sequence_number and returns the next integer."""
    if not tasks:
        return 1
    return max(task.get("sequence_number", 0) for task in tasks) + 1

def load_tasks(customer_dir: Path) -> List[Dict]:
    """Loads tasks from the customer's tasks.json file."""
    tasks_file = customer_dir / "tasks" / "tasks.json"
    if not tasks_file.exists():
        return []
    try:
        with open(tasks_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

def save_tasks(customer_dir: Path, tasks: List[Dict]):
    """Saves the list of tasks to tasks.json."""
    tasks_dir = customer_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tasks_file = tasks_dir / "tasks.json"
    with open(tasks_file, 'w') as f:
        json.dump(tasks, f, indent=2)

def add_new_task(tasks: List[Dict], delta: Dict) -> Dict:
    """
    Creates a new task dictionary from a Gemini delta and adds it to the list.
    Sets created_at, updated_at, and is_dirty flag.
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    seq_num = get_next_sequence_number(tasks)
    
    new_task = {
        "sequence_number": seq_num,
        "title": delta.get("title"),
        "content": delta.get("content"),
        "priority": delta.get("priority", 0),
        "status": 0,  # Default to open
        "created_at": now,
        "updated_at": now,
        "is_dirty": True,
        "provider_id": None, # Generic ID for remote provider
    }
    tasks.append(new_task)
    return new_task

def update_task(tasks: List[Dict], seq_num: int, delta: Dict) -> Optional[Dict]:
    """
    Finds a task by sequence_number, updates it with delta content,
    and flags it as dirty.
    """
    task_to_update = find_task_by_seq(tasks, seq_num)
    if not task_to_update:
        return None

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    # Update fields from delta if they exist
    if "title" in delta:
        task_to_update["title"] = delta["title"]
    if "content" in delta:
        task_to_update["content"] = delta["content"]
    if "priority" in delta:
        task_to_update["priority"] = delta["priority"]
    if "status" in delta:
        task_to_update["status"] = delta["status"]
        
    task_to_update["updated_at"] = now
    task_to_update["is_dirty"] = True
    
    return task_to_update

def find_task_by_seq(tasks: List[Dict], seq_num: int) -> Optional[Dict]:
    """Finds a task in the list by its sequence_number."""
    for task in tasks:
        if task.get("sequence_number") == seq_num:
            return task
    return None

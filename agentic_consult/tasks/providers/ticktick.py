"""TickTick implementation of TaskProvider."""
import json
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List, Optional
import click
import os
import datetime

from agentic_consult.tasks.providers import TaskProvider
from agentic_consult.tasks import add_new_task, get_next_sequence_number

from agentic_consult.config import load_main_config

class TicktickProvider(TaskProvider):
    def __init__(self):
        config = load_main_config() or {}
        self.project = config.get("tasks", {}).get("default_project", "Work")

    def _get_env(self) -> dict:
        env = os.environ.copy()
        # Logic to inject token from Gemini settings if needed (copied from original)
        gemini_settings = Path.home() / ".gemini" / "settings.json"
        if gemini_settings.exists() and "TICKTICK_ACCESS_TOKEN" not in env:
            try:
                with open(gemini_settings, 'r') as f:
                    settings = json.load(f)
                    token = settings.get("mcpServers", {}).get("ticktick", {}).get("env", {}).get("TICKTICK_ACCESS_TOKEN")
                    if token:
                        env["TICKTICK_ACCESS_TOKEN"] = token
            except Exception:
                pass
        return env

    def _run_cmd(self, cmd: List[str]) -> Optional[str]:
        if not shutil.which("ticktick"):
            return None
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, env=self._get_env())
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            click.echo(f"TickTick CLI error: {e.stderr}", err=True)
            return None

    def _fetch_remote_tasks(self, project: str) -> List[Dict]:
        cmd = ["ticktick", "tasks", "list", project, "--format", "json"]
        output = self._run_cmd(cmd)
        if not output:
            return []
        try:
            data = json.loads(output)
            if isinstance(data, dict) and "tasks" in data:
                return data["tasks"]
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    def create_task(self, task: Dict) -> Optional[str]:
        # 'ticktick tasks create TITLE --project ...'
        cmd = ["ticktick", "tasks", "create", task["title"], "--project", self.project]
        if task.get("content"):
            cmd.extend(["--content", task["content"]])
        if task.get("priority"):
            cmd.extend(["--priority", str(task["priority"])])
            
        output = self._run_cmd(cmd)
        
        # Parse output for "Task ID: <ID>"
        if output:
            for line in output.splitlines():
                if "Task ID:" in line:
                    return line.split("Task ID:")[-1].strip()
        return None

    def update_task(self, provider_id: str, task: Dict) -> bool:
        cmd = ["ticktick", "tasks", "update", provider_id, "--project", self.project]
        if task.get("title"):
             cmd.extend(["--title", task["title"]])
        if task.get("content"):
             cmd.extend(["--content", task["content"]])
        if "priority" in task:
             cmd.extend(["--priority", str(task["priority"])])
        if "status" in task:
             cmd.extend(["--status", str(task["status"])])
        
        return self._run_cmd(cmd) is not None

    def sync(self, tasks: List[Dict]) -> bool:
        # 1. Sync Local -> Remote (Dirty tasks)
        for task in tasks:
            if task.get("is_dirty"):
                if not task.get("provider_id"):
                    # Create
                    pid = self.create_task(task)
                    if pid:
                        task["provider_id"] = pid
                        task["is_dirty"] = False
                        task["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                else:
                    # Update
                    if self.update_task(task["provider_id"], task):
                        task["is_dirty"] = False
                        task["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # 2. Sync Remote -> Local (Fetch new remote tasks)
        remote_tasks = self._fetch_remote_tasks(self.project)
        local_map = {t.get("provider_id"): t for t in tasks if t.get("provider_id")}
        
        for rt in remote_tasks:
            rid = rt.get("id")
            if rid not in local_map:
                # New remote task -> Create local
                # We need to manually construct the local task dict structure
                # utilizing add_new_task helper or similar logic manually
                seq_num = get_next_sequence_number(tasks)
                new_task = {
                    "sequence_number": seq_num,
                    "title": rt.get("title"),
                    "content": rt.get("content", ""),
                    "priority": rt.get("priority", 0),
                    "status": rt.get("status", 0),
                    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), # approximate
                    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "is_dirty": False, # It matches remote
                    "provider_id": rid
                }
                tasks.append(new_task)
            else:
                # Update local from remote if local is NOT dirty
                local_task = local_map[rid]
                if not local_task.get("is_dirty"):
                    # Update fields
                    local_task["title"] = rt.get("title")
                    local_task["content"] = rt.get("content", "")
                    local_task["priority"] = rt.get("priority", 0)
                    local_task["status"] = rt.get("status", 0)
                    local_task["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        return True
"""GCP implementation using gcloud CLI subprocess calls."""
import json
import subprocess
import sys
from typing import Optional, List, Dict, Any

from .base import CloudProvider


def _run_cmd(cmd: List[str], capture: bool = False) -> subprocess.CompletedProcess:
    """Run a shell command with consistent error handling."""
    if not capture:
        print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    return subprocess.run(cmd, check=True, capture_output=capture, text=True)


class GCloudProvider(CloudProvider):
    """
    Real GCP implementation using gcloud CLI.

    All operations shell out to gcloud subprocess calls.
    """

    # --- Project Operations ---

    def lookup_project_by_label(self, label_key: str, label_value: str) -> str:
        try:
            res = _run_cmd([
                "gcloud", "projects", "list",
                f"--filter=labels.{label_key}={label_value}",
                "--format=value(projectId)"
            ], capture=True)
            ids = res.stdout.strip().splitlines()
            return ids[0] if ids else ""
        except subprocess.CalledProcessError:
            return ""

    def get_current_account(self) -> str:
        try:
            res = _run_cmd([
                "gcloud", "config", "get-value", "account"
            ], capture=True)
            output = res.stdout.strip()
            if output == "(unset)":
                return "none (not logged in)"
            return output
        except FileNotFoundError:
            return "none (gcloud not installed)"
        except subprocess.CalledProcessError:
            return "unknown error"

    def project_exists(self, project_id: str) -> bool:
        try:
            _run_cmd([
                "gcloud", "projects", "describe", project_id,
                "--format=value(projectId)"
            ], capture=True)
            return True
        except subprocess.CalledProcessError:
            return False

    # --- Bucket Operations ---

    def lookup_bucket_by_label(self, project_id: str, label_key: str, label_value: str) -> str:
        try:
            res = _run_cmd([
                "gcloud", "storage", "buckets", "list",
                f"--project={project_id}",
                f"--filter=labels.{label_key}={label_value}",
                "--format=value(name)"
            ], capture=True)
            names = res.stdout.strip().splitlines()
            if len(names) > 1:
                raise ValueError(f"Multiple buckets found with label {label_key}={label_value}")
            return names[0] if names else ""
        except subprocess.CalledProcessError:
            return ""

    def bucket_exists(self, project_id: str, bucket_name: str) -> bool:
        try:
            _run_cmd([
                "gcloud", "storage", "buckets", "describe",
                f"gs://{bucket_name}", f"--project={project_id}"
            ], capture=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def create_bucket(self, project_id: str, bucket_name: str) -> None:
        _run_cmd([
            "gcloud", "storage", "buckets", "create",
            f"gs://{bucket_name}", f"--project={project_id}"
        ])

    def update_bucket_labels(self, bucket_name: str, labels: Dict[str, str]) -> None:
        label_str = ",".join(f"{k}={v}" for k, v in labels.items())
        _run_cmd([
            "gcloud", "storage", "buckets", "update",
            f"gs://{bucket_name}", f"--update-labels={label_str}"
        ])

    def remove_bucket_labels(self, bucket_name: str, label_keys: List[str]) -> None:
        _run_cmd([
            "gcloud", "storage", "buckets", "update",
            f"gs://{bucket_name}", f"--remove-labels={','.join(label_keys)}"
        ])

    # --- Secret Operations ---

    def secret_exists(self, project_id: str, secret_id: str) -> bool:
        try:
            _run_cmd([
                "gcloud", "secrets", "describe", secret_id,
                f"--project={project_id}"
            ], capture=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def get_secret_value(self, project_id: str, secret_id: str, version: str = "latest") -> Optional[str]:
        try:
            res = _run_cmd([
                "gcloud", "secrets", "versions", "access", version,
                f"--secret={secret_id}", f"--project={project_id}"
            ], capture=True)
            return res.stdout.strip()
        except subprocess.CalledProcessError:
            return None

    def create_secret(self, project_id: str, secret_id: str, value: bytes) -> None:
        subprocess.run(
            ["gcloud", "secrets", "create", secret_id,
             f"--project={project_id}", "--replication-policy=automatic", "--data-file=-"],
            input=value, check=True
        )

    def add_secret_version(self, project_id: str, secret_id: str, value: bytes) -> None:
        subprocess.run(
            ["gcloud", "secrets", "versions", "add", secret_id,
             f"--project={project_id}", "--data-file=-"],
            input=value, check=True
        )

    def set_secret_value(self, project_id: str, secret_id: str, value: str) -> None:
        """Create or update a secret value (convenience method)."""
        val = value.encode() if isinstance(value, str) else value
        if self.secret_exists(project_id, secret_id):
            self.add_secret_version(project_id, secret_id, val)
        else:
            self.create_secret(project_id, secret_id, val)

    # --- Image Operations ---

    def image_exists(self, project_id: str, image_name: str) -> bool:
        try:
            _run_cmd([
                "gcloud", "container", "images", "describe",
                f"gcr.io/{project_id}/{image_name}:latest",
                f"--project={project_id}"
            ], capture=True)
            return True
        except subprocess.CalledProcessError:
            return False

    # --- Cloud Run Operations ---

    def get_cloud_run_job(self, project_id: str, job_name: str, location: str = "us-central1") -> Optional[Dict[str, Any]]:
        try:
            res = _run_cmd([
                "gcloud", "run", "jobs", "describe", job_name,
                f"--project={project_id}", f"--region={location}", "--format=json"
            ], capture=True)
            return json.loads(res.stdout)
        except subprocess.CalledProcessError:
            return None

    # --- Scheduler Operations ---

    def get_scheduler_job(self, project_id: str, job_name: str, location: str = "us-central1") -> Optional[Dict[str, Any]]:
        try:
            res = _run_cmd([
                "gcloud", "scheduler", "jobs", "describe", job_name,
                f"--project={project_id}", f"--location={location}", "--format=json"
            ], capture=True)
            return json.loads(res.stdout)
        except subprocess.CalledProcessError:
            return None

    def update_scheduler_schedule(self, project_id: str, job_name: str, schedule: str, location: str = "us-central1") -> None:
        _run_cmd([
            "gcloud", "scheduler", "jobs", "update", "http", job_name,
            f"--project={project_id}", f"--location={location}",
            f"--schedule={schedule}"
        ])

    def pause_scheduler_job(self, project_id: str, job_name: str, location: str = "us-central1") -> None:
        _run_cmd([
            "gcloud", "scheduler", "jobs", "pause", job_name,
            f"--project={project_id}", f"--location={location}"
        ])

    def resume_scheduler_job(self, project_id: str, job_name: str, location: str = "us-central1") -> None:
        _run_cmd([
            "gcloud", "scheduler", "jobs", "resume", job_name,
            f"--project={project_id}", f"--location={location}"
        ])

    def run_scheduler_job(self, project_id: str, job_name: str, location: str = "us-central1") -> None:
        _run_cmd([
            "gcloud", "scheduler", "jobs", "run", job_name,
            f"--project={project_id}", f"--location={location}"
        ])

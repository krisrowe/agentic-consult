"""In-memory cloud provider for testing without GCP access."""
from pathlib import Path
from typing import Optional, List, Dict, Any
import yaml

from .base import CloudProvider

# Resolve tests/config/cloud/ relative to this file
_CONFIG_DIR = Path(__file__).parent.parent.parent / "tests" / "config" / "cloud"


class DummyCloudProvider(CloudProvider):
    """
    In-memory fake for testing CLI commands without GCP.

    Load from config file:
        provider = DummyCloudProvider.from_config("labeled-project")
        # loads tests/config/cloud/labeled-project.yaml

    Or pre-populate directly:
        provider = DummyCloudProvider()
        provider.projects["my-project"] = {"labels": {"agentic-consult": "default"}}
    """

    @classmethod
    def from_config(cls, name: str) -> "DummyCloudProvider":
        """Load provider state from tests/config/cloud/{name}.yaml"""
        path = _CONFIG_DIR / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Cloud config not found: {path}")
        return cls.from_file(path)

    @classmethod
    def from_file(cls, path: Path) -> "DummyCloudProvider":
        """Load provider state from a YAML file."""
        data = yaml.safe_load(path.read_text())
        provider = cls()
        provider.projects = data.get("projects", {})
        provider.buckets = data.get("buckets", {})
        provider.secrets = data.get("secrets", {})
        provider.images = data.get("images", {})
        provider.scheduler_jobs = data.get("scheduler_jobs", {})
        return provider

    def __init__(self):
        # {project_id: {"labels": {key: value}}}
        self.projects: Dict[str, Dict[str, Any]] = {}

        # {bucket_name: {"project": str, "labels": {key: value}}}
        self.buckets: Dict[str, Dict[str, Any]] = {}

        # {secret_id: {"project": str, "value": bytes}}
        self.secrets: Dict[str, Dict[str, Any]] = {}

        # {image_name: {"project": str}}
        self.images: Dict[str, Dict[str, Any]] = {}

        # {job_name: {"project": str, "location": str, "schedule": str, "state": str, "timeZone": str}}
        self.scheduler_jobs: Dict[str, Dict[str, Any]] = {}

    # --- Project Operations ---

    def lookup_project_by_label(self, label_key: str, label_value: str) -> str:
        for pid, data in self.projects.items():
            if data.get("labels", {}).get(label_key) == label_value:
                return pid
        return ""

    def project_exists(self, project_id: str) -> bool:
        return project_id in self.projects

    # --- Bucket Operations ---

    def lookup_bucket_by_label(self, project_id: str, label_key: str, label_value: str) -> str:
        matches = []
        for name, data in self.buckets.items():
            if data.get("project") == project_id:
                if data.get("labels", {}).get(label_key) == label_value:
                    matches.append(name)
        if len(matches) > 1:
            raise ValueError(f"Multiple buckets found with label {label_key}={label_value}")
        return matches[0] if matches else ""

    def bucket_exists(self, project_id: str, bucket_name: str) -> bool:
        bucket = self.buckets.get(bucket_name)
        return bucket is not None and bucket.get("project") == project_id

    def create_bucket(self, project_id: str, bucket_name: str) -> None:
        self.buckets[bucket_name] = {"project": project_id, "labels": {}}

    def update_bucket_labels(self, bucket_name: str, labels: Dict[str, str]) -> None:
        if bucket_name not in self.buckets:
            raise ValueError(f"Bucket {bucket_name} not found")
        self.buckets[bucket_name].setdefault("labels", {}).update(labels)

    def remove_bucket_labels(self, bucket_name: str, label_keys: List[str]) -> None:
        if bucket_name not in self.buckets:
            raise ValueError(f"Bucket {bucket_name} not found")
        for key in label_keys:
            self.buckets[bucket_name].get("labels", {}).pop(key, None)

    # --- Secret Operations ---

    def secret_exists(self, project_id: str, secret_id: str) -> bool:
        secret = self.secrets.get(secret_id)
        return secret is not None and secret.get("project") == project_id

    def get_secret_value(self, project_id: str, secret_id: str, version: str = "latest") -> Optional[str]:
        secret = self.secrets.get(secret_id)
        if secret and secret.get("project") == project_id:
            val = secret.get("value")
            if isinstance(val, bytes):
                return val.decode()
            return val
        return None

    def create_secret(self, project_id: str, secret_id: str, value: bytes) -> None:
        self.secrets[secret_id] = {"project": project_id, "value": value}

    def add_secret_version(self, project_id: str, secret_id: str, value: bytes) -> None:
        if secret_id not in self.secrets:
            raise ValueError(f"Secret {secret_id} not found")
        self.secrets[secret_id]["value"] = value

    # --- Image Operations ---

    def image_exists(self, project_id: str, image_name: str) -> bool:
        image = self.images.get(image_name)
        return image is not None and image.get("project") == project_id

    # --- Scheduler Operations ---

    def get_scheduler_job(self, project_id: str, job_name: str, location: str = "us-central1") -> Optional[Dict[str, Any]]:
        job = self.scheduler_jobs.get(job_name)
        if job and job.get("project") == project_id and job.get("location") == location:
            return {
                "schedule": job.get("schedule", ""),
                "state": job.get("state", "ENABLED"),
                "timeZone": job.get("timeZone", "UTC"),
            }
        return None

    def update_scheduler_schedule(self, project_id: str, job_name: str, schedule: str, location: str = "us-central1") -> None:
        if job_name not in self.scheduler_jobs:
            raise ValueError(f"Scheduler job {job_name} not found")
        self.scheduler_jobs[job_name]["schedule"] = schedule

    def pause_scheduler_job(self, project_id: str, job_name: str, location: str = "us-central1") -> None:
        if job_name not in self.scheduler_jobs:
            raise ValueError(f"Scheduler job {job_name} not found")
        self.scheduler_jobs[job_name]["state"] = "PAUSED"

    def resume_scheduler_job(self, project_id: str, job_name: str, location: str = "us-central1") -> None:
        if job_name not in self.scheduler_jobs:
            raise ValueError(f"Scheduler job {job_name} not found")
        self.scheduler_jobs[job_name]["state"] = "ENABLED"

    def run_scheduler_job(self, project_id: str, job_name: str, location: str = "us-central1") -> None:
        # Just validate the job exists
        if job_name not in self.scheduler_jobs:
            raise ValueError(f"Scheduler job {job_name} not found")
        # No-op for dummy - real impl triggers execution

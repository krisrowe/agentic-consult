"""Abstract base class for cloud provider operations."""
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any


class CloudProvider(ABC):
    """
    Abstract interface for cloud operations (GCP).

    Enables testing CLI commands like `cloud init` without
    subprocess calls to gcloud or real GCP resources.
    """

    # --- Project Operations ---

    @abstractmethod
    def lookup_project_by_label(self, label_key: str, label_value: str) -> str:
        """Find project ID by label. Returns empty string if not found."""
        pass

    @abstractmethod
    def project_exists(self, project_id: str) -> bool:
        """Check if project exists and is accessible."""
        pass

    # --- Bucket Operations ---

    @abstractmethod
    def lookup_bucket_by_label(self, project_id: str, label_key: str, label_value: str) -> str:
        """Find bucket name by label. Returns empty string if not found."""
        pass

    @abstractmethod
    def bucket_exists(self, project_id: str, bucket_name: str) -> bool:
        """Check if bucket exists."""
        pass

    @abstractmethod
    def create_bucket(self, project_id: str, bucket_name: str) -> None:
        """Create a new bucket."""
        pass

    @abstractmethod
    def update_bucket_labels(self, bucket_name: str, labels: Dict[str, str]) -> None:
        """Add/update labels on a bucket."""
        pass

    @abstractmethod
    def remove_bucket_labels(self, bucket_name: str, label_keys: List[str]) -> None:
        """Remove labels from a bucket."""
        pass

    # --- Secret Operations ---

    @abstractmethod
    def secret_exists(self, project_id: str, secret_id: str) -> bool:
        """Check if secret exists in Secret Manager."""
        pass

    @abstractmethod
    def get_secret_value(self, project_id: str, secret_id: str, version: str = "latest") -> Optional[str]:
        """Get secret value. Returns None if not found."""
        pass

    @abstractmethod
    def create_secret(self, project_id: str, secret_id: str, value: bytes) -> None:
        """Create a new secret with initial version."""
        pass

    @abstractmethod
    def add_secret_version(self, project_id: str, secret_id: str, value: bytes) -> None:
        """Add new version to existing secret."""
        pass

    # --- Image Operations ---

    @abstractmethod
    def image_exists(self, project_id: str, image_name: str) -> bool:
        """Check if container image exists in GCR."""
        pass

    # --- Cloud Run Operations ---

    @abstractmethod
    def get_cloud_run_job(self, project_id: str, job_name: str, location: str = "us-central1") -> Optional[Dict[str, Any]]:
        """Get Cloud Run job details. Returns None if not found."""
        pass

    # --- Scheduler Operations ---

    @abstractmethod
    def get_scheduler_job(self, project_id: str, job_name: str, location: str = "us-central1") -> Optional[Dict[str, Any]]:
        """Get scheduler job details. Returns None if not found."""
        pass

    @abstractmethod
    def update_scheduler_schedule(self, project_id: str, job_name: str, schedule: str, location: str = "us-central1") -> None:
        """Update scheduler job cron expression."""
        pass

    @abstractmethod
    def pause_scheduler_job(self, project_id: str, job_name: str, location: str = "us-central1") -> None:
        """Pause a scheduler job."""
        pass

    @abstractmethod
    def resume_scheduler_job(self, project_id: str, job_name: str, location: str = "us-central1") -> None:
        """Resume a paused scheduler job."""
        pass

    @abstractmethod
    def run_scheduler_job(self, project_id: str, job_name: str, location: str = "us-central1") -> None:
        """Trigger immediate execution of a scheduler job."""
        pass

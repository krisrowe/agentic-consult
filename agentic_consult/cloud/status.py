"""Read-only cloud status checking.

This module provides functions to check the status of cloud resources
without modifying any state. Safe for repeated calls.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple

from .base import CloudProvider


@dataclass
class ResourceStatus:
    """Status of a single cloud resource."""
    name: str
    status: str  # "found", "exists", "missing", "error", "separator"
    id: Optional[str] = None
    changed: bool = False
    change_type: Optional[str] = None  # "created", "labeled", "updated"
    guidance: Optional[str] = None


@dataclass
class CloudStatus:
    """Complete cloud environment status."""
    pre_deploy: List[ResourceStatus] = field(default_factory=list)  # Required before deploy
    deploy: List[ResourceStatus] = field(default_factory=list)  # Created by terraform
    guidance: List[str] = field(default_factory=list)  # Ordered summary guidance
    deploy_ready: bool = False
    config_saved: bool = False

    def _resource_to_dict(self, r: ResourceStatus) -> Dict[str, Any]:
        return {
            "name": r.name,
            "status": r.status,
            "id": r.id,
            "changed": r.changed,
            "change_type": r.change_type,
            "guidance": r.guidance,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "pre_deploy": [self._resource_to_dict(r) for r in self.pre_deploy],
            "deploy": [self._resource_to_dict(r) for r in self.deploy],
            "guidance": self.guidance,
            "deploy_ready": self.deploy_ready,
            "config_saved": self.config_saved,
        }


# Required resources for deployment
REQUIRED_SECRETS = ["gemini-api-key", "gmail-token"]
CLOUD_RUN_JOBS = {
    "fetcher": "gmex-fetcher",
    "analyzer": "consult-analyzer",
}
SCHEDULER_JOBS = {
    "fetcher": "trigger-email-fetch",
    "analyzer": "trigger-email-analysis",
}


def load_images_config() -> dict:
    """Load image definitions from deploy/images.ini."""
    import configparser
    from pathlib import Path
    config_path = Path(__file__).parent.parent.parent / "deploy" / "images.ini"
    parser = configparser.ConfigParser()
    parser.read(config_path)

    images = {}
    for section in parser.sections():
        images[section] = dict(parser[section])
    return images


def is_internal_image(info: dict) -> bool:
    """Check if image is internal (has target = built in this repo)."""
    return "target" in info


def read_cloud_status(
    provider: Optional[CloudProvider] = None,
    project_id: Optional[str] = None,
    bucket_name: Optional[str] = None,
) -> CloudStatus:
    """Read cloud environment status (read-only, no mutations).

    Checks:
    - Project exists
    - Bucket exists and is labeled
    - Secrets exist
    - Images exist in GCR
    - Scheduler jobs exist and their state

    Args:
        provider: Cloud provider instance (defaults to get_cloud_provider())
        project_id: GCP project ID (defaults to settings)
        bucket_name: Bucket name (defaults to settings)

    Returns:
        CloudStatus with all resource statuses
    """
    from ..paths import APP_SLUG, load_settings
    from .factory import get_cloud_provider as _get_cloud_provider

    # Load from settings if not provided
    if project_id is None or bucket_name is None:
        settings = load_settings()
        if project_id is None:
            project_id = settings.get("project_id")
        if bucket_name is None:
            bucket_name = settings.get("bucket_name")

    if provider is None:
        provider = _get_cloud_provider()

    pre_deploy = []
    deploy = []
    all_ready = True
    needs_init = False
    missing_images = []

    # Handle missing project_id
    if not project_id:
        pre_deploy.append(ResourceStatus(
            name="project",
            status="missing",
            guidance="Run: ./cloud init",
        ))
        return CloudStatus(
            pre_deploy=pre_deploy,
            deploy=[],
            guidance=["./cloud init"],
            deploy_ready=False,
            config_saved=False,
        )

    # 1. Check project
    if provider.project_exists(project_id):
        pre_deploy.append(ResourceStatus(
            name="project",
            status="found",
            id=project_id,
        ))
    else:
        pre_deploy.append(ResourceStatus(
            name="project",
            status="missing",
            id=project_id,
            guidance="Project not found or not accessible",
        ))
        all_ready = False

    # 2. Check bucket
    labeled_bucket = provider.lookup_bucket_by_label(project_id, APP_SLUG, "default")
    if labeled_bucket:
        pre_deploy.append(ResourceStatus(
            name="bucket",
            status="found",
            id=labeled_bucket,
        ))
    elif bucket_name and provider.bucket_exists(project_id, bucket_name):
        pre_deploy.append(ResourceStatus(
            name="bucket",
            status="found",
            id=bucket_name,
            guidance=f"Bucket exists but missing {APP_SLUG} label",
        ))
    else:
        pre_deploy.append(ResourceStatus(
            name="bucket",
            status="missing",
            guidance="./cloud init",
        ))
        needs_init = True
        all_ready = False

    # 3. Check secrets
    for secret_id in REQUIRED_SECRETS:
        if provider.secret_exists(project_id, secret_id):
            pre_deploy.append(ResourceStatus(
                name=secret_id,
                status="exists",
            ))
        else:
            pre_deploy.append(ResourceStatus(
                name=secret_id,
                status="missing",
                guidance="./cloud init",
            ))
            needs_init = True
            all_ready = False

    # 4. Check images (from deploy/images.ini)
    images_config = load_images_config()
    for name, info in images_config.items():
        image_name = info["image"]

        if provider.image_exists(project_id, image_name):
            pre_deploy.append(ResourceStatus(
                name=image_name,
                status="exists",
            ))
        else:
            pre_deploy.append(ResourceStatus(
                name=image_name,
                status="missing",
                guidance=f"./cloud images deploy {name}",
            ))
            missing_images.append(name)
            all_ready = False

    # 5. Check Cloud Run jobs (deploy phase - created by terraform)
    deploy_missing = False
    for alias, job_name in CLOUD_RUN_JOBS.items():
        job = provider.get_cloud_run_job(project_id, job_name)
        if job:
            deploy.append(ResourceStatus(
                name=f"cloud run:{alias}",
                status="exists",
                id=job_name,
            ))
        else:
            deploy.append(ResourceStatus(
                name=f"cloud run:{alias}",
                status="missing",
                id=job_name,
            ))
            deploy_missing = True

    # 6. Check scheduler jobs (deploy phase - created by terraform)
    for alias, job_name in SCHEDULER_JOBS.items():
        job = provider.get_scheduler_job(project_id, job_name)
        if job:
            state = job.get("state", "UNKNOWN")
            deploy.append(ResourceStatus(
                name=f"scheduler:{alias}",
                status=state.lower(),
                id=job_name,
            ))
        else:
            deploy.append(ResourceStatus(
                name=f"scheduler:{alias}",
                status="missing",
                id=job_name,
            ))
            deploy_missing = True

    # Set deploy guidance based on overall pre-deploy readiness
    for r in deploy:
        if r.status == "missing":
            if all_ready:
                r.guidance = "(terraform - see below)"
            else:
                r.guidance = "(fix above first)"

    # Build consolidated guidance array (ordered by priority)
    guidance = []
    if needs_init:
        guidance.append("./cloud init")
    if missing_images:
        guidance.append("./cloud images deploy all --if-missing")

    # If deploy ready and terraform resources need setup, show terraform commands
    if all_ready and deploy_missing:
        from pathlib import Path
        terraform_dir = Path(__file__).parent.parent.parent / "deploy" / "terraform"
        # Make path home-relative if possible
        home = Path.home()
        try:
            tf_path = "~/" + str(terraform_dir.relative_to(home))
        except ValueError:
            tf_path = str(terraform_dir)
        guidance.append(f"cd {tf_path}")
        guidance.append("terraform init")
        guidance.append(f'terraform apply -var="project_id={project_id}" -var="bucket_name={bucket_name}"')

    return CloudStatus(
        pre_deploy=pre_deploy,
        deploy=deploy,
        guidance=guidance,
        deploy_ready=all_ready,
    )

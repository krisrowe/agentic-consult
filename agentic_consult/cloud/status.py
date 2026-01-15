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
    status: str  # "found", "exists", "missing", "error"
    id: Optional[str] = None
    changed: bool = False
    change_type: Optional[str] = None  # "created", "labeled", "updated"
    guidance: Optional[str] = None


@dataclass
class CloudStatus:
    """Complete cloud environment status."""
    resources: List[ResourceStatus] = field(default_factory=list)
    deploy_ready: bool = False
    config_saved: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "resources": [
                {
                    "name": r.name,
                    "status": r.status,
                    "id": r.id,
                    "changed": r.changed,
                    "change_type": r.change_type,
                    "guidance": r.guidance,
                }
                for r in self.resources
            ],
            "deploy_ready": self.deploy_ready,
            "config_saved": self.config_saved,
        }


# Required resources for deployment
REQUIRED_SECRETS = ["gemini-api-key", "gmail-token"]
REQUIRED_IMAGES = ["gmex-fetcher", "consult-analyzer"]
SCHEDULER_JOBS = {
    "fetcher": "trigger-email-fetch",
    "analyzer": "trigger-email-analysis",
}


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

    resources = []
    all_ready = True

    # Handle missing project_id
    if not project_id:
        resources.append(ResourceStatus(
            name="project",
            status="missing",
            guidance="Run: ./cloud init",
        ))
        return CloudStatus(
            resources=resources,
            deploy_ready=False,
            config_saved=False,
        )

    # 1. Check project
    if provider.project_exists(project_id):
        resources.append(ResourceStatus(
            name="project",
            status="found",
            id=project_id,
        ))
    else:
        resources.append(ResourceStatus(
            name="project",
            status="missing",
            id=project_id,
            guidance="Project not found or not accessible",
        ))
        all_ready = False

    # 2. Check bucket
    labeled_bucket = provider.lookup_bucket_by_label(project_id, APP_SLUG, "default")
    if labeled_bucket:
        resources.append(ResourceStatus(
            name="bucket",
            status="found",
            id=labeled_bucket,
        ))
    elif bucket_name and provider.bucket_exists(project_id, bucket_name):
        resources.append(ResourceStatus(
            name="bucket",
            status="found",
            id=bucket_name,
            guidance=f"Bucket exists but missing {APP_SLUG} label",
        ))
    else:
        resources.append(ResourceStatus(
            name="bucket",
            status="missing",
            guidance="Run: ./cloud init",
        ))
        all_ready = False

    # 3. Check secrets
    for secret_id in REQUIRED_SECRETS:
        if provider.secret_exists(project_id, secret_id):
            resources.append(ResourceStatus(
                name=secret_id,
                status="exists",
            ))
        else:
            resources.append(ResourceStatus(
                name=secret_id,
                status="missing",
                guidance="Run: ./cloud init",
            ))
            all_ready = False

    # 4. Check images
    for image_name in REQUIRED_IMAGES:
        if provider.image_exists(project_id, image_name):
            resources.append(ResourceStatus(
                name=image_name,
                status="exists",
            ))
        else:
            if image_name == "gmex-fetcher":
                guidance = "cd <path-to>/gmail-extractor && make push"
            else:
                guidance = "./cloud image build && ./cloud image push"
            resources.append(ResourceStatus(
                name=image_name,
                status="missing",
                guidance=guidance,
            ))
            all_ready = False

    # 5. Check scheduler jobs
    for alias, job_name in SCHEDULER_JOBS.items():
        job = provider.get_scheduler_job(project_id, job_name)
        if job:
            state = job.get("state", "UNKNOWN")
            resources.append(ResourceStatus(
                name=f"scheduler:{alias}",
                status=state.lower(),
                id=job_name,
            ))
        else:
            resources.append(ResourceStatus(
                name=f"scheduler:{alias}",
                status="missing",
                id=job_name,
                guidance="Created by terraform (run pre-deploy for commands)",
            ))
            # Scheduler jobs are created by deploy, not a blocker for deploy

    return CloudStatus(
        resources=resources,
        deploy_ready=all_ready,
    )


@dataclass
class PreDeployResult:
    """Result from pre_deploy check."""
    ready: bool
    status: CloudStatus
    terraform_commands: Optional[List[str]] = None
    terraform_vars: Optional[Dict[str, str]] = None
    issues: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result = {
            "ready": self.ready,
            "status": self.status.to_dict(),
        }
        if self.ready:
            result["terraform_commands"] = self.terraform_commands
            result["terraform_vars"] = self.terraform_vars
        else:
            result["issues"] = self.issues
        return result


def pre_deploy(
    provider: CloudProvider,
    project_id: str,
    bucket_name: str,
) -> PreDeployResult:
    """Check deploy readiness and return terraform commands if ready.

    Args:
        provider: Cloud provider instance
        project_id: GCP project ID
        bucket_name: GCS bucket name

    Returns:
        PreDeployResult with status, and either terraform commands (if ready)
        or list of issues (if not ready)
    """
    status = read_cloud_status(provider, project_id, bucket_name)
    status.config_saved = True

    if not status.deploy_ready:
        issues = [
            f"{r.name}: {r.guidance}"
            for r in status.resources
            if r.status == "missing" and r.guidance
        ]
        return PreDeployResult(
            ready=False,
            status=status,
            issues=issues,
        )

    # Ready - provide terraform commands
    terraform_vars = {
        "project_id": project_id,
        "bucket_name": bucket_name,
    }
    terraform_commands = [
        "cd deploy/terraform",
        "terraform init",
        f'terraform apply -var="project_id={project_id}" -var="bucket_name={bucket_name}"',
    ]

    return PreDeployResult(
        ready=True,
        status=status,
        terraform_commands=terraform_commands,
        terraform_vars=terraform_vars,
    )

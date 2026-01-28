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
class GuidanceGroup:
    """A group of guidance items with optional heading."""
    items: List[str]
    heading: Optional[str] = None


@dataclass
class CloudStatus:
    """Complete cloud environment status."""
    pre_deploy: List[ResourceStatus] = field(default_factory=list)  # Required before deploy
    deploy: List[ResourceStatus] = field(default_factory=list)  # Created by terraform
    guidance: List[GuidanceGroup] = field(default_factory=list)  # Grouped guidance
    status: str = "not_deploy_ready"  # "not_deploy_ready", "deploy_ready", "deployed"

    def _resource_to_dict(self, r: ResourceStatus) -> Dict[str, Any]:
        return {
            "name": r.name,
            "status": r.status,
            "id": r.id,
            "changed": r.changed,
            "change_type": r.change_type,
            "guidance": r.guidance,
        }

    def _guidance_to_dict(self, g: GuidanceGroup) -> Dict[str, Any]:
        result = {"items": g.items}
        if g.heading:
            result["heading"] = g.heading
        return result

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "pre_deploy": [self._resource_to_dict(r) for r in self.pre_deploy],
            "deploy": [self._resource_to_dict(r) for r in self.deploy],
            "guidance": [self._guidance_to_dict(g) for g in self.guidance],
            "status": self.status,
        }


# Required resources for deployment (not managed by terraform)
REQUIRED_SECRETS = ["gemini-api-key", "gmail-token"]


def load_terraform_state() -> Optional[Dict[str, Any]]:
    """Load terraform state from local file.

    Returns:
        Parsed tfstate dict, or None if not found/invalid.
    """
    import json
    from pathlib import Path

    tfstate_path = Path(__file__).parent.parent.parent / "deploy" / "terraform" / "terraform.tfstate"
    if not tfstate_path.exists():
        return None

    try:
        with open(tfstate_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def format_tf_resource(resource: Dict[str, Any]) -> Optional[Tuple[str, str, Optional[str]]]:
    """Format a terraform resource for status display.

    Args:
        resource: Resource dict from terraform state.

    Returns:
        Tuple of (display_name, status, id) or None to suppress.
    """
    rtype = resource.get("type", "")
    name = resource.get("name", "")
    instances = resource.get("instances", [])

    if not instances:
        return None

    attrs = instances[0].get("attributes", {})

    # Cloud Run Jobs
    if rtype == "google_cloud_run_v2_job":
        job_name = attrs.get("name", name)
        return (f"run:{job_name}", "exists", job_name)

    # Cloud Run Services
    elif rtype == "google_cloud_run_v2_service":
        svc_name = attrs.get("name", name)
        return (f"run:{svc_name}", "exists", svc_name)

    # Scheduler Jobs
    elif rtype == "google_cloud_scheduler_job":
        job_name = attrs.get("name", name)
        state = attrs.get("state", "UNKNOWN").lower()
        return (f"sched:{job_name}", state, job_name)

    # Service Accounts
    elif rtype == "google_service_account":
        account_id = attrs.get("account_id", name)
        return (f"svc account", "exists", account_id)

    # Storage Buckets - skip, shown in pre-deploy via API
    elif rtype == "google_storage_bucket":
        return None

    # IAM bindings - suppress (rolled into svc account conceptually)
    elif rtype.endswith("_iam_member"):
        return None

    # Unknown - show raw
    else:
        return (f"{rtype}.{name}", "exists", None)


def refresh_terraform_state(project_id: str, bucket_name: str) -> Tuple[bool, Optional[str]]:
    """Run terraform refresh to update state from cloud.

    Args:
        project_id: GCP project ID for -var flag.
        bucket_name: Bucket name for -var flag.

    Returns:
        Tuple of (success, error_message).
    """
    import subprocess
    from pathlib import Path

    terraform_dir = Path(__file__).parent.parent.parent / "deploy" / "terraform"

    # Check if terraform is initialized
    if not (terraform_dir / ".terraform").exists():
        return False, "Terraform not initialized. Run ./cloud deploy first."

    cmd = [
        "terraform", "refresh",
        f"-var=project_id={project_id}",
        f"-var=bucket_name={bucket_name}",
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=terraform_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            # Strip ANSI codes and get first meaningful line
            import re
            stderr = re.sub(r'\x1b\[[0-9;]*m', '', result.stderr)
            # Find first line with actual content
            for line in stderr.split('\n'):
                line = line.strip().lstrip('│').strip()
                if line and not line.startswith('╷') and not line.startswith('╵'):
                    return False, line[:80]  # Truncate long messages
            return False, "Terraform refresh failed"
        return True, None
    except subprocess.TimeoutExpired:
        return False, "Terraform refresh timed out"
    except FileNotFoundError:
        return False, "Terraform not found in PATH"
    except Exception as e:
        return False, str(e)


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
    refresh: bool = True,
) -> CloudStatus:
    """Read cloud environment status (read-only, no mutations).

    Checks:
    - Project exists
    - Bucket exists and is labeled
    - Secrets exist
    - Images exist in GCR
    - Terraform-managed resources (from state)

    Args:
        provider: Cloud provider instance (defaults to get_cloud_provider())
        project_id: GCP project ID (defaults to settings)
        bucket_name: Bucket name (defaults to settings)
        refresh: If True (default), run terraform refresh before reading state.
                 If False, use cached state file (faster but may be stale).

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
    pre_deploy_complete = True
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
            guidance=[GuidanceGroup(items=["./cloud init"])],
            status="not_deploy_ready",
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
        pre_deploy_complete = False

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
        pre_deploy_complete = False

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
            pre_deploy_complete = False

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
            pre_deploy_complete = False

    # 5. Check terraform-managed resources (deploy phase)
    deploy_missing = False
    refresh_warning = None

    # Optionally refresh terraform state before reading
    if refresh and project_id and bucket_name:
        success, error = refresh_terraform_state(project_id, bucket_name)
        if not success:
            refresh_warning = error

    tf_state = load_terraform_state()

    if refresh_warning and tf_state:
        # Refresh failed but we have cached state - show warning
        deploy.append(ResourceStatus(
            name="terraform state",
            status="cached",
            guidance=f"Refresh failed: {refresh_warning}",
        ))

    if tf_state:
        resources = tf_state.get("resources", [])
        for resource in resources:
            formatted = format_tf_resource(resource)
            if formatted:
                display_name, status, res_id = formatted
                deploy.append(ResourceStatus(
                    name=display_name,
                    status=status,
                    id=res_id,
                ))
        # If we have tf state but no deploy resources, something's off
        if not deploy:
            deploy_missing = True
    else:
        # No terraform state - indicate deploy needed
        deploy.append(ResourceStatus(
            name="terraform",
            status="not initialized",
            guidance="./cloud deploy",
        ))
        deploy_missing = True

    # Set deploy guidance based on overall pre-deploy readiness
    for r in deploy:
        if r.status == "missing":
            if pre_deploy_complete:
                r.guidance = "(terraform - see below)"
            else:
                r.guidance = "(fix above first)"

    # Build consolidated guidance groups (ordered by priority)
    guidance = []

    # Pre-deploy fixes needed
    if needs_init or missing_images:
        items = []
        if needs_init:
            items.append("./cloud init")
        if missing_images:
            items.append("./cloud images deploy all --if-missing")
        guidance.append(GuidanceGroup(items=items))

    # Deploy guidance
    if pre_deploy_complete and deploy_missing:
        # Main path
        guidance.append(GuidanceGroup(items=["./cloud deploy"]))
        # Cautious path
        guidance.append(GuidanceGroup(
            heading="Preview first:",
            items=["./cloud deploy --plan"]
        ))
        # Manual path
        from pathlib import Path
        terraform_dir = Path(__file__).parent.parent.parent / "deploy" / "terraform"
        home = Path.home()
        try:
            tf_path = "~/" + str(terraform_dir.relative_to(home))
        except ValueError:
            tf_path = str(terraform_dir)
        guidance.append(GuidanceGroup(
            heading="Manual:",
            items=[
                f"cd {tf_path}",
                "terraform init",
                f'terraform apply -var="project_id={project_id}" -var="bucket_name={bucket_name}"',
            ]
        ))
    elif pre_deploy_complete and not deploy_missing:
        # Fully deployed - show validation/redeploy options
        guidance.append(GuidanceGroup(
            heading="Validate:",
            items=["./cloud deploy --plan"]
        ))
        guidance.append(GuidanceGroup(
            heading="Test:",
            items=[
                "./cloud scheduler run fetcher",
                "./cloud scheduler run analyzer",
            ]
        ))
        guidance.append(GuidanceGroup(
            heading="Redeploy:",
            items=[
                "./cloud images deploy all",
                "./cloud deploy",
            ]
        ))

    # Determine overall status
    if pre_deploy_complete and not deploy_missing:
        status = "deployed"
    elif pre_deploy_complete:
        status = "deploy_ready"
    else:
        status = "not_deploy_ready"

    return CloudStatus(
        pre_deploy=pre_deploy,
        deploy=deploy,
        guidance=guidance,
        status=status,
    )

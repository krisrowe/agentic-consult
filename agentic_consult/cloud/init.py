"""Cloud environment initialization logic.

This module contains the core init logic, separated from CLI concerns.
Both ./cloud init and tests call this directly.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable

from .base import CloudProvider
from .status import read_cloud_status, CloudStatus
from ..paths import APP_SLUG


@dataclass
class InitResult:
    """Result of cloud init operation."""
    success: bool
    project_id: Optional[str] = None
    bucket_name: Optional[str] = None
    operations: list = None
    error: Optional[str] = None
    status: Optional[CloudStatus] = None

    def __post_init__(self):
        if self.operations is None:
            self.operations = []

    def to_dict(self) -> dict:
        result = {
            "success": self.success,
            "project_id": self.project_id,
            "bucket_name": self.bucket_name,
            "operations": self.operations,
        }
        if self.error:
            result["error"] = self.error
        if self.status:
            result["status"] = self.status.to_dict()
        return result


@dataclass
class InitOptions:
    """Options for cloud init."""
    project: Optional[str] = None
    bucket: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gmail_token_path: Optional[str] = None
    allow_create_bucket: bool = False
    allow_change_bucket: bool = False


class InitContext:
    """Callbacks for interactive prompts and logging.

    In non-interactive mode, prompt callbacks should return None.
    """
    def __init__(
        self,
        prompt_secret: Optional[Callable[[str], Optional[str]]] = None,
        prompt_path: Optional[Callable[[str], Optional[str]]] = None,
        confirm: Optional[Callable[[str], bool]] = None,
        log: Optional[Callable[[str], None]] = None,
    ):
        self.prompt_secret = prompt_secret or (lambda _: None)
        self.prompt_path = prompt_path or (lambda _: None)
        self.confirm = confirm or (lambda _: False)
        self.log = log or (lambda _: None)


def cloud_init(
    provider: CloudProvider,
    options: InitOptions,
    existing_config: dict,
    context: InitContext,
) -> InitResult:
    """Initialize cloud environment.

    Args:
        provider: Cloud provider instance
        options: Init options (project, bucket, secrets, flags)
        existing_config: Existing settings dict (project_id, bucket_name)
        context: Callbacks for prompts and logging

    Returns:
        InitResult with success/failure and operations performed
    """
    # --- PHASE 1: VERIFICATION (READ-ONLY) ---

    # 1. Resolve Project: options > existing config > label discovery
    project_id = (
        options.project or
        existing_config.get("project_id") or
        provider.lookup_project_by_label(APP_SLUG, "default")
    )

    if not project_id:
        return InitResult(
            success=False,
            error="Could not determine Project ID. Pass --project or label your project."
        )

    # 2. Validate project exists (if from config, might be stale/inaccessible)
    if not options.project and existing_config.get("project_id"):
        if not provider.project_exists(project_id):
            return InitResult(
                success=False,
                project_id=project_id,
                error=f"Configured project '{project_id}' not found or not accessible. "
                      "Verify your access or use --project to specify a different one."
            )

    # 3. Validate Gemini API Key
    api_key_value = options.gemini_api_key
    if not provider.secret_exists(project_id, "gemini-api-key") and not api_key_value:
        api_key_value = context.prompt_secret(
            "Required Secret 'gemini-api-key' is missing. Enter value"
        )
        if not api_key_value:
            return InitResult(
                success=False,
                project_id=project_id,
                error="'gemini-api-key' secret missing and no value provided."
            )

    # 4. Validate Gmail Token
    token_data = None
    gmail_token_path = options.gmail_token_path
    if not provider.secret_exists(project_id, "gmail-token") and not gmail_token_path:
        gmail_token_path = context.prompt_path(
            "Required Secret 'gmail-token' is missing. Enter path to token.json file"
        )
        if not gmail_token_path:
            return InitResult(
                success=False,
                project_id=project_id,
                error="'gmail-token' secret missing and no path provided."
            )

    if gmail_token_path:
        path = Path(gmail_token_path).expanduser()
        if not path.exists():
            return InitResult(
                success=False,
                project_id=project_id,
                error=f"Gmail token file not found at {path}"
            )
        token_data = path.read_bytes()

    # 5. Validate Bucket Logic
    labeled_bucket = provider.lookup_bucket_by_label(project_id, APP_SLUG, "default")
    target_bucket = options.bucket or labeled_bucket or f"consult-data-{project_id}"

    do_unlabel_old = False
    if labeled_bucket and options.bucket and labeled_bucket != options.bucket:
        if not options.allow_change_bucket:
            if not context.confirm(
                f"Bucket '{labeled_bucket}' is active. Switch label to '{options.bucket}'?"
            ):
                return InitResult(
                    success=False,
                    project_id=project_id,
                    error=f"Bucket '{labeled_bucket}' is already active. "
                          "Pass --allow-change-bucket to switch."
                )
        do_unlabel_old = True

    do_create_bucket = False
    if not provider.bucket_exists(project_id, target_bucket):
        if not options.allow_create_bucket:
            if not context.confirm(f"Bucket '{target_bucket}' does not exist. Create it?"):
                return InitResult(
                    success=False,
                    project_id=project_id,
                    error=f"Bucket '{target_bucket}' does not exist. "
                          "Pass --allow-create-bucket to create."
                )
        do_create_bucket = True

    # --- PHASE 2: EXECUTION (WRITE-ONLY) ---
    ops = []
    context.log(f"Applying changes to project: {project_id}...")

    # 1. Handle Bucket
    if do_unlabel_old:
        context.log(f"Unlabeling {labeled_bucket}...")
        provider.remove_bucket_labels(labeled_bucket, [APP_SLUG])
        ops.append({"op": "bucket_unlabeled", "bucket": labeled_bucket})

    if do_create_bucket:
        context.log(f"Creating gs://{target_bucket}...")
        provider.create_bucket(project_id, target_bucket)
        ops.append({"op": "bucket_created", "bucket": target_bucket})

    # Only label if not already labeled
    if labeled_bucket != target_bucket:
        context.log(f"Ensuring {target_bucket} is labeled...")
        provider.update_bucket_labels(target_bucket, {APP_SLUG: "default"})
        ops.append({"op": "bucket_labeled", "bucket": target_bucket})

    # 2. Handle Secrets
    if api_key_value:
        if not provider.secret_exists(project_id, "gemini-api-key"):
            context.log("Creating secret 'gemini-api-key'...")
            provider.create_secret(project_id, "gemini-api-key", api_key_value.encode())
            ops.append({"op": "secret_created", "secret": "gemini-api-key"})
        else:
            context.log("Updating secret 'gemini-api-key'...")
            provider.add_secret_version(project_id, "gemini-api-key", api_key_value.encode())
            ops.append({"op": "secret_updated", "secret": "gemini-api-key"})

    if token_data:
        if not provider.secret_exists(project_id, "gmail-token"):
            context.log("Creating secret 'gmail-token'...")
            provider.create_secret(project_id, "gmail-token", token_data)
            ops.append({"op": "secret_created", "secret": "gmail-token"})
        else:
            context.log("Updating secret 'gmail-token'...")
            provider.add_secret_version(project_id, "gmail-token", token_data)
            ops.append({"op": "secret_updated", "secret": "gmail-token"})

    # 3. Get final status
    status = read_cloud_status(provider, project_id, target_bucket)

    return InitResult(
        success=True,
        project_id=project_id,
        bucket_name=target_bucket,
        operations=ops,
        status=status,
    )

"""Pydantic schema for email.yaml configuration.

Used for validation on REST API uploads and runtime loading.
"""

from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class RuleMatch(BaseModel):
    """Match criteria for an email rule."""
    model_config = ConfigDict(extra="forbid")

    from_: Optional[str] = Field(None, alias="from")
    subject: Optional[str] = None


class EmailRule(BaseModel):
    """A single email processing rule."""
    model_config = ConfigDict(extra="forbid")

    id: str
    action: str = "review"  # archive, review, track_as_task, archive_now
    match: Optional[RuleMatch] = None
    condition: Optional[str] = None
    instructions: Optional[str] = None
    disabled: bool = False


class EmailSettings(BaseModel):
    """User settings for email processing."""
    model_config = ConfigDict(extra="forbid")

    timezone: Optional[str] = None
    pool_size: Optional[int] = Field(None, ge=1, le=100)
    batch_target: Optional[int] = Field(None, ge=1, le=50)


class EmailConfig(BaseModel):
    """Complete email.yaml configuration schema."""
    model_config = ConfigDict(extra="forbid")

    settings: Optional[EmailSettings] = None
    rules: list[EmailRule] = []
    enable: list[str] = []
    disable: list[str] = []


def validate_email_config(data: dict) -> EmailConfig:
    """Validate email config dict against schema.

    Raises pydantic.ValidationError if invalid.
    """
    return EmailConfig.model_validate(data)

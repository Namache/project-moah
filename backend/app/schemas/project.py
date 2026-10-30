import re
from datetime import datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.schemas.common import UtcModel, clean_optional
from app.schemas.task import clean_prefix

ProjectStatus = Literal["active", "paused", "completed", "archived"]


def clean_name(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned or len(cleaned) > 120:
        raise ValueError("name must contain 1 to 120 non-whitespace characters")
    return cleaned


def clean_root_path(value: str | None) -> str | None:
    cleaned = clean_optional(value)
    if cleaned is not None:
        if "\x00" in cleaned or not Path(cleaned).is_absolute():
            raise ValueError("root_path must be an absolute filesystem path")
    return cleaned


def clean_accent(value: str | None) -> str | None:
    cleaned = clean_optional(value)
    if cleaned is not None and re.fullmatch(r"#[0-9a-fA-F]{6}", cleaned) is None:
        raise ValueError("accent must be a six-digit hexadecimal color, such as #336699")
    return cleaned


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = Field(default=None, max_length=2000)
    icon: str | None = Field(default=None, max_length=40)
    accent: str | None = Field(default=None, max_length=40)
    root_path: str | None = Field(default=None, max_length=4096)
    task_prefix: str | None = None
    status: ProjectStatus = "active"

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return clean_name(value)

    @field_validator("description", "icon")
    @classmethod
    def normalize_optional(cls, value: str | None) -> str | None:
        return clean_optional(value)

    @field_validator("accent")
    @classmethod
    def validate_accent(cls, value: str | None) -> str | None:
        return clean_accent(value)

    @field_validator("root_path")
    @classmethod
    def validate_root_path(cls, value: str | None) -> str | None:
        return clean_root_path(value)

    @field_validator("task_prefix")
    @classmethod
    def validate_task_prefix(cls, value: str | None) -> str | None:
        return clean_prefix(value)


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    icon: str | None = Field(default=None, max_length=40)
    accent: str | None = Field(default=None, max_length=40)
    root_path: str | None = Field(default=None, max_length=4096)
    task_prefix: str | None = None
    status: ProjectStatus | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("name cannot be null")
        return clean_name(value)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: ProjectStatus | None) -> ProjectStatus:
        if value is None:
            raise ValueError("status cannot be null")
        return value

    @field_validator("description", "icon")
    @classmethod
    def normalize_optional(cls, value: str | None) -> str | None:
        return clean_optional(value)

    @field_validator("accent")
    @classmethod
    def validate_accent(cls, value: str | None) -> str | None:
        return clean_accent(value)

    @field_validator("root_path")
    @classmethod
    def validate_root_path(cls, value: str | None) -> str | None:
        return clean_root_path(value)

    @field_validator("task_prefix")
    @classmethod
    def validate_task_prefix(cls, value: str | None) -> str | None:
        return clean_prefix(value)

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one project field is required")
        return self


class ProjectRead(UtcModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    description: str | None
    icon: str | None
    accent: str | None
    root_path: str | None
    task_prefix: str | None
    status: ProjectStatus
    current_focus_task_id: str | None
    created_at: datetime
    updated_at: datetime
    last_opened_at: datetime | None
    archived_at: datetime | None

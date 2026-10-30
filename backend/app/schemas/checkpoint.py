"""Checkpoint payloads and compact task context."""

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import UtcModel, clean_optional
from app.schemas.task import TaskRef, clean_title

TEXT_LIMIT = 20000


class CheckpointCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str | None = Field(default=None, min_length=1, max_length=64)
    title: str
    summary: str = Field(default="", max_length=TEXT_LIMIT)
    completed_work: str = Field(default="", max_length=TEXT_LIMIT)
    remaining_work: str = Field(default="", max_length=TEXT_LIMIT)
    problems: str = Field(default="", max_length=TEXT_LIMIT)
    next_steps: str = Field(default="", max_length=TEXT_LIMIT)
    agent: str | None = Field(default=None, max_length=120)
    git_commit: str | None = Field(default=None, max_length=64)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return clean_title(value)

    @field_validator("agent", "git_commit")
    @classmethod
    def normalize_optional(cls, value: str | None) -> str | None:
        return clean_optional(value)


class CheckpointUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = None
    summary: str | None = Field(default=None, max_length=TEXT_LIMIT)
    completed_work: str | None = Field(default=None, max_length=TEXT_LIMIT)
    remaining_work: str | None = Field(default=None, max_length=TEXT_LIMIT)
    problems: str | None = Field(default=None, max_length=TEXT_LIMIT)
    next_steps: str | None = Field(default=None, max_length=TEXT_LIMIT)
    agent: str | None = Field(default=None, max_length=120)
    git_commit: str | None = Field(default=None, max_length=64)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        return None if value is None else clean_title(value)

    @field_validator("agent", "git_commit")
    @classmethod
    def normalize_optional(cls, value: str | None) -> str | None:
        return clean_optional(value)

    @model_validator(mode="after")
    def check(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one checkpoint field is required")
        for field in (
            "title",
            "summary",
            "completed_work",
            "remaining_work",
            "problems",
            "next_steps",
        ):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class CheckpointRead(UtcModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    task_id: str | None
    task: TaskRef | None = None
    title: str
    summary: str
    completed_work: str
    remaining_work: str
    problems: str
    next_steps: str
    agent: str | None
    git_commit: str | None
    created_at: datetime
    updated_at: datetime

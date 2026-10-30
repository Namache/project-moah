from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import UtcModel, clean_optional
from app.schemas.image import ImageRead
from app.schemas.task import TaskRef, clean_tag, clean_title

MemoryType = Literal["decision", "rule", "fact", "idea", "bug", "note", "warning"]
MemoryStatus = Literal["active", "superseded", "invalidated", "archived"]
Importance = Literal["low", "normal", "high", "critical"]
AiVisibility = Literal["always", "relevant_only", "manual_only", "hidden"]
MemorySort = Literal["priority", "updated_desc", "updated_asc", "title_asc"]
# Who is acting. Humans may override a lock; every other actor may not.
Actor = str
HUMAN = "human"


class MemoryFields(BaseModel):
    @field_validator("title", check_fields=False)
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        return None if value is None else clean_title(value)

    @field_validator("source_type", "source_reference", check_fields=False)
    @classmethod
    def normalize(cls, value: str | None) -> str | None:
        return clean_optional(value)

    @field_validator("tags", check_fields=False)
    @classmethod
    def validate_tags(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else [clean_tag(item) for item in value]


class MemoryCreate(MemoryFields):
    model_config = ConfigDict(extra="forbid")

    type: MemoryType
    title: str
    content: str = Field(default="", max_length=20000)
    importance: Importance = "normal"
    ai_visibility: AiVisibility = "relevant_only"
    is_pinned: bool = False
    is_locked: bool = False
    is_resolved: bool = False
    source_type: str | None = Field(default=None, max_length=40)
    source_reference: str | None = Field(default=None, max_length=2000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    tags: list[str] = Field(default_factory=list, max_length=30)
    task_ids: list[str] = Field(default_factory=list, max_length=50)
    # Other memories of the same project this one relates to, by ID such as DEC-003.
    related: list[str] = Field(default_factory=list, max_length=20)


class MemoryLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    related: str = Field(min_length=1, max_length=64)


class MemoryUpdate(MemoryFields):
    """The type of a memory never changes; create a new one instead."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    content: str | None = Field(default=None, max_length=20000)
    importance: Importance | None = None
    ai_visibility: AiVisibility | None = None
    is_pinned: bool | None = None
    is_locked: bool | None = None
    is_resolved: bool | None = None
    pending_note: str | None = Field(default=None, max_length=2000)
    source_type: str | None = Field(default=None, max_length=40)
    source_reference: str | None = Field(default=None, max_length=2000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    tags: list[str] | None = Field(default=None, max_length=30)
    task_ids: list[str] | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def check(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one memory field is required")
        for field in (
            "title",
            "content",
            "importance",
            "ai_visibility",
            "is_pinned",
            "is_locked",
            "is_resolved",
            "tags",
            "task_ids",
        ):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class MemorySupersede(MemoryFields):
    """The replacement. Its type defaults to the memory being replaced."""

    model_config = ConfigDict(extra="forbid")

    title: str
    content: str = Field(default="", max_length=20000)
    importance: Importance | None = None
    ai_visibility: AiVisibility | None = None
    is_locked: bool | None = None


class MemoryRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    human_id: str
    type: MemoryType
    title: str
    status: MemoryStatus


class MemoryRead(UtcModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    human_id: str
    type: MemoryType
    title: str
    content: str
    status: MemoryStatus
    importance: Importance
    is_pinned: bool
    is_locked: bool
    is_resolved: bool = False
    pending_note: str | None = None
    ai_visibility: AiVisibility
    source_type: str | None
    source_reference: str | None
    confidence: float | None
    supersedes_id: str | None
    created_at: datetime
    updated_at: datetime
    invalidated_at: datetime | None
    archived_at: datetime | None
    tags: list[str] = Field(default_factory=list)
    tasks: list[TaskRef] = Field(default_factory=list)
    superseded_by: MemoryRef | None = None
    supersedes: MemoryRef | None = None
    related: list[MemoryRef] = Field(default_factory=list)
    images: list[ImageRead] = Field(default_factory=list)


class MemoryHistory(BaseModel):
    """The whole supersession chain, oldest first. ``current_id`` is its newest memory."""

    chain: list[MemoryRef]
    current_id: str


class MemoryCounts(BaseModel):
    by_type: dict[str, int]
    pinned: int
    locked: int

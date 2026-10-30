import re
from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import UtcModel, clean_optional
from app.schemas.image import ImageRead

MilestoneStatus = Literal["planned", "active", "completed", "archived"]
TaskStatus = Literal["backlog", "todo", "in_progress", "blocked", "review", "completed", "archived"]
TaskPriority = Literal["low", "normal", "high", "critical"]
# Read as "this task <type> the other task". "child", "blocks" and "superseded_by" are
# the inverse views of "parent", "depends_on" and "supersedes".
RelationshipType = Literal[
    "parent", "child", "depends_on", "blocks", "related_to", "supersedes", "superseded_by"
]

PREFIX_PATTERN = re.compile(r"[A-Z][A-Z0-9]{0,9}")


def clean_title(value: str, *, limit: int = 200) -> str:
    cleaned = " ".join(value.split())
    if not cleaned or len(cleaned) > limit:
        raise ValueError(f"must contain 1 to {limit} non-whitespace characters")
    return cleaned


def clean_prefix(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().upper()
    if PREFIX_PATTERN.fullmatch(cleaned) is None:
        raise ValueError("prefix must be 1 to 10 letters or digits and start with a letter")
    return cleaned


def clean_tag(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned or len(cleaned) > 40:
        raise ValueError("tags must contain 1 to 40 non-whitespace characters")
    return cleaned


def _forbid_null(model: BaseModel, fields: tuple[str, ...]) -> None:
    for field in fields:
        if field in model.model_fields_set and getattr(model, field) is None:
            raise ValueError(f"{field} cannot be null")


# ---- Milestones -------------------------------------------------------------------------


class MilestoneCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = Field(default=None, max_length=4000)
    status: MilestoneStatus = "planned"
    target_date: date | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return clean_title(value, limit=120)

    @field_validator("description")
    @classmethod
    def normalize(cls, value: str | None) -> str | None:
        return clean_optional(value)


class MilestoneUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = Field(default=None, max_length=4000)
    status: MilestoneStatus | None = None
    target_date: date | None = None
    sort_order: int | None = Field(default=None, ge=0)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return None if value is None else clean_title(value, limit=120)

    @field_validator("description")
    @classmethod
    def normalize(cls, value: str | None) -> str | None:
        return clean_optional(value)

    @model_validator(mode="after")
    def check(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one milestone field is required")
        _forbid_null(self, ("name", "status", "sort_order"))
        return self


class MilestoneRead(UtcModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    name: str
    description: str | None
    status: MilestoneStatus
    target_date: date | None
    sort_order: int
    created_at: datetime
    updated_at: datetime
    task_count: int = 0
    completed_task_count: int = 0


# ---- Acceptance criteria ----------------------------------------------------------------


class CriterionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    is_completed: bool = False

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return clean_title(value, limit=1000)


class CriterionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None = None
    is_completed: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        return None if value is None else clean_title(value, limit=1000)

    @model_validator(mode="after")
    def check(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one criterion field is required")
        _forbid_null(self, ("description", "is_completed", "sort_order"))
        return self


class CriterionRead(UtcModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    description: str
    is_completed: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


# ---- Tasks ------------------------------------------------------------------------------


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str | None = Field(default=None, max_length=20000)
    prefix: str | None = None
    status: TaskStatus = "todo"
    priority: TaskPriority = "normal"
    milestone_id: str | None = None
    next_action: str | None = Field(default=None, max_length=2000)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return clean_title(value)

    @field_validator("description", "next_action", "milestone_id")
    @classmethod
    def normalize(cls, value: str | None) -> str | None:
        return clean_optional(value)

    @field_validator("prefix")
    @classmethod
    def validate_prefix(cls, value: str | None) -> str | None:
        return clean_prefix(value)

    @field_validator("acceptance_criteria")
    @classmethod
    def validate_criteria(cls, value: list[str]) -> list[str]:
        return [clean_title(item, limit=1000) for item in value]

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str]) -> list[str]:
        return [clean_tag(item) for item in value]


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    description: str | None = Field(default=None, max_length=20000)
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    milestone_id: str | None = None
    next_action: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = Field(default=None, max_length=30)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        return None if value is None else clean_title(value)

    @field_validator("description", "next_action", "milestone_id")
    @classmethod
    def normalize(cls, value: str | None) -> str | None:
        return clean_optional(value)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else [clean_tag(item) for item in value]

    @model_validator(mode="after")
    def check(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one task field is required")
        _forbid_null(self, ("title", "status", "priority", "tags"))
        return self


class TaskMove(BaseModel):
    """Board drag-and-drop: put a task at ``index`` within the ``status`` column."""

    model_config = ConfigDict(extra="forbid")

    status: TaskStatus
    index: int = Field(ge=0)


class TaskRef(BaseModel):
    """Compact task identity, used in relationship and summary payloads."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    human_id: str
    title: str
    status: TaskStatus


class RelationshipCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: RelationshipType
    # The other task, as an internal id or a human ID such as "SAVE-009".
    target: str = Field(min_length=1, max_length=64)


class RelationshipRead(BaseModel):
    """A relationship as seen from the task being read."""

    id: str
    type: RelationshipType
    task: TaskRef


class TaskSummary(UtcModel):
    """List and board row: everything a card shows, without nested detail."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    milestone_id: str | None
    human_id: str
    title: str
    status: TaskStatus
    priority: TaskPriority
    next_action: str | None
    sort_order: int
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    archived_at: datetime | None
    criteria_total: int = 0
    criteria_completed: int = 0
    tags: list[str] = Field(default_factory=list)
    is_focus: bool = False
    is_blocked_by_open_dependency: bool = False


class TaskDetail(TaskSummary):
    description: str | None
    acceptance_criteria: list[CriterionRead]
    relationships: list[RelationshipRead]
    milestone: MilestoneRead | None = None
    images: list[ImageRead] = Field(default_factory=list)


class WorkspaceTask(TaskSummary):
    """A task in the cross-project view, carrying its project identity."""

    project_name: str
    project_icon: str | None
    project_accent: str | None


class ProjectOverview(BaseModel):
    project_id: str
    task_counts: dict[str, int]
    focus_task: TaskSummary | None
    active_milestone: MilestoneRead | None

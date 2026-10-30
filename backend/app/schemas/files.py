from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import UtcModel, clean_optional
from app.schemas.memory import MemoryRef
from app.schemas.task import TaskRef


class SymbolIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="symbol", min_length=1, max_length=40)
    summary: str | None = Field(default=None, max_length=1000)

    @field_validator("name", "kind")
    @classmethod
    def strip(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator("summary")
    @classmethod
    def normalize(cls, value: str | None) -> str | None:
        return clean_optional(value)


class SymbolRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    kind: str
    summary: str | None


class FileFields(BaseModel):
    @field_validator("purpose", "summary", "language", check_fields=False)
    @classmethod
    def normalize(cls, value: str | None) -> str | None:
        return clean_optional(value)


class FileCreate(FileFields):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=1024)
    language: str | None = Field(default=None, max_length=40)
    purpose: str | None = Field(default=None, max_length=2000)
    summary: str | None = Field(default=None, max_length=8000)
    symbols: list[SymbolIn] = Field(default_factory=list, max_length=200)
    task_ids: list[str] = Field(default_factory=list, max_length=50)
    memory_ids: list[str] = Field(default_factory=list, max_length=50)
    checkpoint_ids: list[str] = Field(default_factory=list, max_length=50)


class FileUpdate(FileFields):
    """Lists replace the whole set; leave a field out to keep it as it is."""

    model_config = ConfigDict(extra="forbid")

    language: str | None = Field(default=None, max_length=40)
    purpose: str | None = Field(default=None, max_length=2000)
    summary: str | None = Field(default=None, max_length=8000)
    symbols: list[SymbolIn] | None = Field(default=None, max_length=200)
    task_ids: list[str] | None = Field(default=None, max_length=50)
    memory_ids: list[str] | None = Field(default=None, max_length=50)
    checkpoint_ids: list[str] | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def check(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one file field is required")
        for field in ("symbols", "task_ids", "memory_ids", "checkpoint_ids"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class CheckpointRef(BaseModel):
    id: str
    title: str


class FileRead(UtcModel):
    id: str
    project_id: str
    path: str
    language: str | None
    purpose: str | None
    summary: str | None
    last_seen_hash: str | None
    # True when the file changed since it was last reviewed. None when it cannot be checked.
    stale: bool | None = None
    created_at: datetime
    updated_at: datetime
    symbols: list[SymbolRead] = Field(default_factory=list)
    tasks: list[TaskRef] = Field(default_factory=list)
    memories: list[MemoryRef] = Field(default_factory=list)
    checkpoints: list[CheckpointRef] = Field(default_factory=list)


GitState = Literal[
    "ok",
    "no_path",
    "path_missing",
    "not_shared",
    "git_missing",
    "not_repo",
    "unsafe_repo",
    "timeout",
    "error",
]


class ChangedFile(BaseModel):
    path: str
    status: str  # a short label: modified, added, deleted, renamed, untracked, conflicted


class GitStatus(BaseModel):
    state: GitState
    message: str
    root_path: str | None = None
    branch: str | None = None
    detached: bool = False
    head: str | None = None
    head_subject: str | None = None
    clean: bool | None = None
    changed: list[ChangedFile] = Field(default_factory=list)
    changed_total: int = 0
    warnings: list[str] = Field(default_factory=list)


class CommitTaskRead(BaseModel):
    task: TaskRef
    status: Literal["confirmed", "suggested"]
    origin: str


class CommitRead(UtcModel):
    sha: str
    short_sha: str
    subject: str
    author: str | None
    committed_at: datetime | None
    files: list[str] = Field(default_factory=list)
    tasks: list[CommitTaskRead] = Field(default_factory=list)
    # False for a commit kept from earlier that the repository no longer reports.
    in_repository: bool = True


class CommitList(BaseModel):
    git: GitStatus
    commits: list[CommitRead]


class FileTreeEntry(BaseModel):
    path: str
    file_id: str | None = None
    has_notes: bool = False
    stale: bool | None = None
    changed: str | None = None


class FileTree(BaseModel):
    git: GitStatus
    entries: list[FileTreeEntry]
    truncated: bool = False
    source: Literal["git", "folder", "notes"]


class CommitLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1, max_length=64)

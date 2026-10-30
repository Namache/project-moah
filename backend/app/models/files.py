"""Phase 7 file knowledge and Git commit metadata.

Only metadata is stored, never source text. Every link table uses composite foreign keys so
a file can only relate to tasks, memory, checkpoints, and commits of its own project.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.project import utc_now


def new_id() -> str:
    return str(uuid4())


class ProjectFile(Base):
    __tablename__ = "project_files"
    __table_args__ = (
        UniqueConstraint("project_id", "path", name="uq_project_files_path"),
        UniqueConstraint("id", "project_id", name="uq_project_files_id_project"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # POSIX path relative to the repository root, validated by the service.
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    language: Mapped[str | None] = mapped_column(String(40))
    purpose: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    last_seen_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class FileSymbol(Base):
    __tablename__ = "file_symbols"
    __table_args__ = (Index("ix_file_symbols_file", "file_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project_files.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="symbol")
    summary: Mapped[str | None] = mapped_column(Text)


def _link(table: str, other: str, other_table: str):
    """Composite-FK link rows between a file and one other project-scoped entity."""
    return (
        ForeignKeyConstraint(
            ["file_id", "project_id"],
            ["project_files.id", "project_files.project_id"],
            ondelete="CASCADE",
            name=f"fk_{table}_file_same_project",
        ),
        ForeignKeyConstraint(
            [other, "project_id"],
            [f"{other_table}.id", f"{other_table}.project_id"],
            ondelete="CASCADE",
            name=f"fk_{table}_{other}_same_project",
        ),
        Index(f"ix_{table}_{other}", other),
    )


class FileTask(Base):
    __tablename__ = "file_tasks"
    __table_args__ = _link("file_tasks", "task_id", "tasks")
    file_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)


class FileMemory(Base):
    __tablename__ = "file_memories"
    __table_args__ = _link("file_memories", "memory_id", "memories")
    file_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    memory_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)


class FileCheckpoint(Base):
    __tablename__ = "file_checkpoints"
    __table_args__ = _link("file_checkpoints", "checkpoint_id", "checkpoints")
    file_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    checkpoint_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)


class GitCommit(Base):
    """Commit metadata kept so history survives a moved or damaged repository."""

    __tablename__ = "git_commits"
    __table_args__ = (
        UniqueConstraint("project_id", "sha", name="uq_git_commits_project_sha"),
        UniqueConstraint("id", "project_id", name="uq_git_commits_id_project"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    sha: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str | None] = mapped_column(String(200))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CommitTask(Base):
    """A commit-to-task association. ``suggested`` links are not treated as established."""

    __tablename__ = "commit_tasks"
    __table_args__ = (
        CheckConstraint("status IN ('confirmed', 'suggested')", name="ck_commit_tasks_status"),
        ForeignKeyConstraint(
            ["commit_id", "project_id"],
            ["git_commits.id", "git_commits.project_id"],
            ondelete="CASCADE",
            name="fk_commit_tasks_commit_same_project",
        ),
        ForeignKeyConstraint(
            ["task_id", "project_id"],
            ["tasks.id", "tasks.project_id"],
            ondelete="CASCADE",
            name="fk_commit_tasks_task_same_project",
        ),
        Index("ix_commit_tasks_task", "task_id"),
    )

    commit_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="confirmed")
    origin: Mapped[str] = mapped_column(String(40), nullable=False, default="human")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CommitFile(Base):
    """Paths a commit touched, kept as text so they do not need an indexed file record."""

    __tablename__ = "commit_files"
    __table_args__ = (
        ForeignKeyConstraint(
            ["commit_id", "project_id"],
            ["git_commits.id", "git_commits.project_id"],
            ondelete="CASCADE",
            name="fk_commit_files_commit_same_project",
        ),
        Index("ix_commit_files_path", "project_id", "path"),
    )

    commit_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    path: Mapped[str] = mapped_column(String(1024), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)

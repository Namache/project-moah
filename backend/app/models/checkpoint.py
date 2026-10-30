"""Phase 4 checkpoints and append-only activity records."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
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

ACTOR_TYPES = ("human", "codex", "claude", "system")


class Checkpoint(Base):
    __tablename__ = "checkpoints"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_checkpoints_id_project"),
        ForeignKeyConstraint(
            ["task_id", "task_project_id"],
            ["tasks.id", "tasks.project_id"],
            ondelete="SET NULL",
            name="fk_checkpoints_task_same_project",
        ),
        CheckConstraint(
            "(task_id IS NULL AND task_project_id IS NULL) OR "
            "(task_id IS NOT NULL AND task_project_id IS NOT NULL "
            "AND task_project_id = project_id)",
            name="ck_checkpoints_task_project",
        ),
        Index("ix_checkpoints_project_created", "project_id", "created_at", "id"),
        Index("ix_checkpoints_task_created", "task_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(String(36))
    task_project_id: Mapped[str | None] = mapped_column(String(36))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    completed_work: Mapped[str] = mapped_column(Text, nullable=False, default="")
    remaining_work: Mapped[str] = mapped_column(Text, nullable=False, default="")
    problems: Mapped[str] = mapped_column(Text, nullable=False, default="")
    next_steps: Mapped[str] = mapped_column(Text, nullable=False, default="")
    agent: Mapped[str | None] = mapped_column(String(120))
    git_commit: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ActivityEvent(Base):
    """Audit trail, not a source for rebuilding application state."""

    __tablename__ = "activity_events"
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('human', 'codex', 'claude', 'system')",
            name="ck_activity_actor_type",
        ),
        ForeignKeyConstraint(
            ["task_id", "task_project_id"],
            ["tasks.id", "tasks.project_id"],
            ondelete="SET NULL",
            name="fk_activity_task_same_project",
        ),
        CheckConstraint(
            "(task_id IS NULL AND task_project_id IS NULL) OR "
            "(task_id IS NOT NULL AND task_project_id IS NOT NULL "
            "AND task_project_id = project_id)",
            name="ck_activity_task_project",
        ),
        Index("ix_activity_project_timestamp", "project_id", "timestamp", "id"),
        Index("ix_activity_timestamp", "timestamp", "id"),
        Index("ix_activity_task_timestamp", "task_id", "timestamp", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(String(36))
    task_project_id: Mapped[str | None] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_name: Mapped[str | None] = mapped_column(String(120))
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

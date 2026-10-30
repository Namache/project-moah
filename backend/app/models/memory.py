"""Phase 3 durable project memory.

Same-project integrity is enforced by composite foreign keys, as for tasks: a memory can
only supersede, link to, or be tagged within its own project.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.project import utc_now

MEMORY_TYPES = ("decision", "rule", "fact", "idea", "bug", "note", "warning")
MEMORY_STATUSES = ("active", "superseded", "invalidated", "archived")
MEMORY_IMPORTANCE = ("low", "normal", "high", "critical")
AI_VISIBILITY = ("always", "relevant_only", "manual_only", "hidden")
TYPE_PREFIXES = {
    "decision": "DEC",
    "rule": "RULE",
    "fact": "FACT",
    "idea": "IDEA",
    "bug": "BUG",
    "note": "NOTE",
    "warning": "WARN",
}


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Memory(Base):
    __tablename__ = "memories"
    __table_args__ = (
        CheckConstraint(_in("type", MEMORY_TYPES), name="ck_memories_type"),
        CheckConstraint(_in("status", MEMORY_STATUSES), name="ck_memories_status"),
        CheckConstraint(_in("importance", MEMORY_IMPORTANCE), name="ck_memories_importance"),
        CheckConstraint(_in("ai_visibility", AI_VISIBILITY), name="ck_memories_visibility"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_memories_confidence",
        ),
        CheckConstraint("supersedes_id IS NULL OR supersedes_id <> id", name="ck_memories_self"),
        UniqueConstraint("project_id", "human_id", name="uq_memories_project_human_id"),
        UniqueConstraint("id", "project_id", name="uq_memories_id_project"),
        # A memory can be replaced only once, so supersession forms chains, not trees.
        UniqueConstraint("supersedes_id", name="uq_memories_one_successor"),
        ForeignKeyConstraint(
            ["supersedes_id", "project_id"],
            ["memories.id", "memories.project_id"],
            name="fk_memories_supersedes_same_project",
        ),
        Index("ix_memories_project_type_status", "project_id", "type", "status"),
        Index("ix_memories_project_status_updated", "project_id", "status", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    human_id: Mapped[str] = mapped_column(String(24), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    importance: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Used by known issues (type "bug"): False is pending, True is resolved.
    is_resolved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    # Why a known issue is still pending after review; a person writes it.
    pending_note: Mapped[str | None] = mapped_column(Text)
    ai_visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="relevant_only")
    source_type: Mapped[str | None] = mapped_column(String(40))
    source_reference: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    supersedes_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MemoryTag(Base):
    __tablename__ = "memory_tags"
    __table_args__ = (
        ForeignKeyConstraint(
            ["memory_id", "project_id"],
            ["memories.id", "memories.project_id"],
            ondelete="CASCADE",
            name="fk_memory_tags_memory_same_project",
        ),
        ForeignKeyConstraint(
            ["tag_id", "project_id"],
            ["tags.id", "tags.project_id"],
            ondelete="CASCADE",
            name="fk_memory_tags_tag_same_project",
        ),
        Index("ix_memory_tags_tag", "tag_id"),
    )

    memory_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tag_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)


class MemoryTask(Base):
    """Links a memory to the tasks it informs."""

    __tablename__ = "memory_tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["memory_id", "project_id"],
            ["memories.id", "memories.project_id"],
            ondelete="CASCADE",
            name="fk_memory_tasks_memory_same_project",
        ),
        ForeignKeyConstraint(
            ["task_id", "project_id"],
            ["tasks.id", "tasks.project_id"],
            ondelete="CASCADE",
            name="fk_memory_tasks_task_same_project",
        ),
        Index("ix_memory_tasks_task", "task_id"),
    )

    memory_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)


class MemoryLink(Base):
    """An undirected link between two memories of the same project, stored once per pair."""

    __tablename__ = "memory_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["memory_id", "project_id"],
            ["memories.id", "memories.project_id"],
            ondelete="CASCADE",
            name="fk_memory_links_memory_same_project",
        ),
        ForeignKeyConstraint(
            ["related_id", "project_id"],
            ["memories.id", "memories.project_id"],
            ondelete="CASCADE",
            name="fk_memory_links_related_same_project",
        ),
        CheckConstraint("memory_id < related_id", name="ck_memory_links_ordered"),
        Index("ix_memory_links_related", "related_id"),
    )

    memory_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    related_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

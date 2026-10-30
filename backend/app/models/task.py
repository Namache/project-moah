"""Phase 2 task-management tables.

Same-project integrity is enforced in the database, not only in services: child rows
reference their parent through composite ``(id, project_id)`` foreign keys, so a task
can never point at another project's milestone, tag, or related task.
"""

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.project import utc_now

MILESTONE_STATUSES = ("planned", "active", "completed", "archived")
TASK_STATUSES = ("backlog", "todo", "in_progress", "blocked", "review", "completed", "archived")
TASK_PRIORITIES = ("low", "normal", "high", "critical")
# Stored relationship types. "child" and "blocks" are accepted by the API and stored as
# their inverse ("parent", "depends_on") with the endpoints swapped.
RELATIONSHIP_TYPES = ("parent", "depends_on", "related_to", "supersedes")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def new_id() -> str:
    return str(uuid4())


class Milestone(Base):
    __tablename__ = "milestones"
    __table_args__ = (
        CheckConstraint(_in("status", MILESTONE_STATUSES), name="ck_milestones_status"),
        UniqueConstraint("id", "project_id", name="uq_milestones_id_project"),
        Index("ix_milestones_project_order", "project_id", "sort_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="planned")
    target_date: Mapped[date | None] = mapped_column(Date)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(_in("status", TASK_STATUSES), name="ck_tasks_status"),
        CheckConstraint(_in("priority", TASK_PRIORITIES), name="ck_tasks_priority"),
        CheckConstraint("number > 0", name="ck_tasks_number"),
        UniqueConstraint("project_id", "human_id", name="uq_tasks_project_human_id"),
        UniqueConstraint("id", "project_id", name="uq_tasks_id_project"),
        ForeignKeyConstraint(
            ["milestone_id", "project_id"],
            ["milestones.id", "milestones.project_id"],
            name="fk_tasks_milestone_same_project",
        ),
        Index("ix_tasks_project_status_order", "project_id", "status", "sort_order"),
        Index("ix_tasks_project_prefix_number", "project_id", "prefix", "number"),
        Index("ix_tasks_milestone", "milestone_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    milestone_id: Mapped[str | None] = mapped_column(String(36))
    prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    human_id: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="todo")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    next_action: Mapped[str | None] = mapped_column(Text)
    # Order within a board column; services renumber a column on every move.
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    criteria: Mapped[list["AcceptanceCriterion"]] = relationship(
        back_populates="task",
        order_by="AcceptanceCriterion.sort_order",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AcceptanceCriterion(Base):
    __tablename__ = "task_acceptance_criteria"
    __table_args__ = (Index("ix_task_criteria_task_order", "task_id", "sort_order"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    task: Mapped[Task] = relationship(back_populates="criteria")


class TaskRelationship(Base):
    __tablename__ = "task_relationships"
    __table_args__ = (
        CheckConstraint(_in("type", RELATIONSHIP_TYPES), name="ck_task_relationships_type"),
        CheckConstraint("source_task_id <> target_task_id", name="ck_task_relationships_not_self"),
        UniqueConstraint(
            "source_task_id", "target_task_id", "type", name="uq_task_relationships_edge"
        ),
        ForeignKeyConstraint(
            ["source_task_id", "project_id"],
            ["tasks.id", "tasks.project_id"],
            ondelete="CASCADE",
            name="fk_task_relationships_source_same_project",
        ),
        ForeignKeyConstraint(
            ["target_task_id", "project_id"],
            ["tasks.id", "tasks.project_id"],
            ondelete="CASCADE",
            name="fk_task_relationships_target_same_project",
        ),
        Index("ix_task_relationships_target", "target_task_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    target_task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("project_id", "name_key", name="uq_tags_project_name"),
        UniqueConstraint("id", "project_id", name="uq_tags_id_project"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    name_key: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TaskTag(Base):
    __tablename__ = "task_tags"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "project_id"],
            ["tasks.id", "tasks.project_id"],
            ondelete="CASCADE",
            name="fk_task_tags_task_same_project",
        ),
        ForeignKeyConstraint(
            ["tag_id", "project_id"],
            ["tags.id", "tags.project_id"],
            ondelete="CASCADE",
            name="fk_task_tags_tag_same_project",
        ),
        Index("ix_task_tags_tag", "tag_id"),
    )

    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tag_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)

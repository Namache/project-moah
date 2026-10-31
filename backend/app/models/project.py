from datetime import UTC, datetime, timedelta
from threading import Lock
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# The reserved row holding rules and memory shared by every project. Never listed as a project.
GLOBAL_PROJECT_ID = "global"


_clock_lock = Lock()
_last_now = datetime.min.replace(tzinfo=UTC)


def utc_now() -> datetime:
    """Always later than the previous call: Windows' clock can return the same time for
    several quick writes, and timelines sort by time."""
    global _last_now
    with _clock_lock:
        now = datetime.now(UTC)
        _last_now = now if now > _last_now else _last_now + timedelta(microseconds=1)
        return _last_now


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'paused', 'completed', 'archived')",
            name="ck_projects_status",
        ),
        CheckConstraint("kind IN ('project', 'global')", name="ck_projects_kind"),
        # The focus task must belong to this project. SQLite skips the check while
        # current_focus_task_id is NULL. use_alter breaks the projects<->tasks cycle.
        ForeignKeyConstraint(
            ["current_focus_task_id", "id"],
            ["tasks.id", "tasks.project_id"],
            name="fk_projects_focus_task_same_project",
            use_alter=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(40), nullable=True)
    accent: Mapped[str | None] = mapped_column(String(40), nullable=True)
    root_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="project")
    # Default prefix for new task IDs, such as "CAMP" in CAMP-037.
    task_prefix: Mapped[str | None] = mapped_column(String(12), nullable=True)
    current_focus_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

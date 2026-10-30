"""Delete tasks that have been Done for two weeks, when the setting asks for it.

The tasks go; what was done stays readable in the activity log, where each deletion is
recorded as Moah's, with the task's id, title and when it was completed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.task import Task
from app.services.activity import acting_as
from app.services.settings import get_task_settings

DONE_RETENTION = timedelta(days=14)
CLEANUP_ACTOR = "moah"


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def delete_old_done_tasks(session: Session, now: datetime | None = None) -> list[str]:
    """Delete every task Done for at least two weeks. Returns the deleted tasks' human ids."""
    from app.services.tasks import TaskService

    settings = get_task_settings(session)
    if not settings.auto_delete_done:
        return []
    now = now or datetime.now(UTC)
    cutoff = now - DONE_RETENTION
    since = _aware(settings.auto_delete_done_since)
    if since is not None and since > cutoff:
        return []
    # Compared in Python: SQLite keeps these as text, with or without a time zone.
    expired = [
        task
        for task in session.scalars(select(Task).where(Task.status == "completed"))
        if (_aware(task.completed_at) or _aware(task.updated_at) or now) <= cutoff
    ]
    deleted = []
    service = TaskService(session)
    with acting_as("system", CLEANUP_ACTOR):
        for task in expired:
            completed = _aware(task.completed_at)
            service.delete(
                task.project_id,
                task.id,
                {
                    "reason": "done_for_two_weeks",
                    "completed_at": completed.isoformat() if completed else None,
                },
            )
            deleted.append(task.human_id)
    return deleted


def cleanup_quietly(session: Session) -> None:
    """Run the clean-up as a side task; never let it break the caller."""
    try:
        delete_old_done_tasks(session)
    except Exception:  # noqa: BLE001 - the clean-up is best effort, it tries again later
        session.rollback()

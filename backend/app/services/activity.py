"""Append-only activity events and project/workspace timeline reads.

``record`` never commits. Callers add the event before committing their domain change so
an action and its audit record succeed or fail together.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.checkpoint import ACTOR_TYPES, ActivityEvent
from app.models.project import Project
from app.schemas.activity import ActivityRead
from app.services.errors import invalid, not_found

EVENT_TYPE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,63}")

# Who is acting, for callers that do not pass an actor. The desktop app leaves this as a
# person; the MCP server sets it for the duration of each tool call, so every record an
# agent causes is attributed to that agent without each service needing an extra argument.
_current_actor: ContextVar[tuple[str, str | None]] = ContextVar("actor", default=("human", None))


@contextmanager
def acting_as(actor_type: str, actor_name: str | None = None) -> Iterator[None]:
    token = _current_actor.set((actor_type, actor_name))
    try:
        yield
    finally:
        _current_actor.reset(token)


def current_actor() -> tuple[str, str | None]:
    return _current_actor.get()


class ActivityService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        project_id: str,
        event_type: str,
        *,
        actor_type: str | None = None,
        actor_name: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> ActivityEvent:
        """Stage an event in the current transaction; the caller commits it."""
        if actor_type is None:
            actor_type, default_name = current_actor()
            actor_name = actor_name or default_name
        if actor_type not in ACTOR_TYPES:
            raise invalid("Unknown activity actor")
        if EVENT_TYPE_PATTERN.fullmatch(event_type) is None:
            raise invalid("Activity event type must be uppercase letters, digits, or underscores")
        if actor_name is not None and len(actor_name) > 120:
            raise invalid("Activity actor name is too long")
        if entity_type is not None and len(entity_type) > 32:
            raise invalid("Activity entity type is too long")
        if entity_id is not None and len(entity_id) > 64:
            raise invalid("Activity entity ID is too long")
        event = ActivityEvent(
            project_id=project_id,
            task_id=task_id,
            task_project_id=project_id if task_id else None,
            event_type=event_type,
            actor_type=actor_type,
            actor_name=actor_name,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata_json=dict(metadata or {}),
            timestamp=timestamp or datetime.now(UTC),
        )
        self.session.add(event)
        return event

    def list(
        self,
        *,
        project_id: str | None = None,
        task: str | None = None,
        event_types: Iterable[str] | None = None,
        actor_types: Iterable[str] | None = None,
        entity_types: Iterable[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ActivityRead]:
        if project_id is not None and self.session.get(Project, project_id) is None:
            raise not_found("Project not found")
        statement = select(ActivityEvent, Project.name).join(
            Project, Project.id == ActivityEvent.project_id
        )
        if project_id is not None:
            statement = statement.where(ActivityEvent.project_id == project_id)
        if task is not None:
            if project_id is None:
                raise invalid("A project is required to filter activity by task")
            # Local import keeps TaskService free to emit events through this service.
            from app.services.tasks import TaskService

            task_id = TaskService(self.session).get(project_id, task).id
            statement = statement.where(ActivityEvent.task_id == task_id)
        if event_types:
            statement = statement.where(ActivityEvent.event_type.in_(list(event_types)))
        if actor_types:
            statement = statement.where(ActivityEvent.actor_type.in_(list(actor_types)))
        if entity_types:
            statement = statement.where(ActivityEvent.entity_type.in_(list(entity_types)))
        rows = self.session.execute(
            statement.order_by(ActivityEvent.timestamp.desc(), ActivityEvent.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [
            ActivityRead(
                id=event.id,
                project_id=event.project_id,
                project_name=project_name,
                task_id=event.task_id,
                event_type=event.event_type,
                actor_type=event.actor_type,
                actor_name=event.actor_name,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                metadata=event.metadata_json,
                timestamp=event.timestamp,
            )
            for event, project_name in rows
        ]

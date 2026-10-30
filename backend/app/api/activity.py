"""Read-only project and workspace activity timelines."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.schemas.activity import ActivityRead, ActorType
from app.services.activity import ActivityService

project_router = APIRouter(prefix="/api/projects/{project_id}/activity", tags=["activity"])
workspace_router = APIRouter(prefix="/api/activity", tags=["activity"])
DatabaseSession = Annotated[Session, Depends(get_session)]


@project_router.get("", response_model=list[ActivityRead])
def list_project_activity(
    project_id: str,
    session: DatabaseSession,
    task: Annotated[str | None, Query(max_length=64)] = None,
    event_types: Annotated[list[str] | None, Query(alias="event_type")] = None,
    actor_types: Annotated[list[ActorType] | None, Query(alias="actor_type")] = None,
    entity_types: Annotated[list[str] | None, Query(alias="entity_type")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ActivityRead]:
    return ActivityService(session).list(
        project_id=project_id,
        task=task,
        event_types=event_types,
        actor_types=actor_types,
        entity_types=entity_types,
        limit=limit,
        offset=offset,
    )


@workspace_router.get("", response_model=list[ActivityRead])
def list_workspace_activity(
    session: DatabaseSession,
    project_id: str | None = None,
    event_types: Annotated[list[str] | None, Query(alias="event_type")] = None,
    actor_types: Annotated[list[ActorType] | None, Query(alias="actor_type")] = None,
    entity_types: Annotated[list[str] | None, Query(alias="entity_type")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ActivityRead]:
    return ActivityService(session).list(
        project_id=project_id,
        event_types=event_types,
        actor_types=actor_types,
        entity_types=entity_types,
        limit=limit,
        offset=offset,
    )

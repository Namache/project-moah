"""Phase 3 routes. The REST API serves the app's own UI, so every call is a human action."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.schemas.memory import (
    AiVisibility,
    MemoryCounts,
    MemoryCreate,
    MemoryHistory,
    MemoryLinkCreate,
    MemoryRead,
    MemorySort,
    MemoryStatus,
    MemorySupersede,
    MemoryType,
    MemoryUpdate,
)
from app.services.discovery import discover_quietly
from app.services.memory import MemoryService

router = APIRouter(prefix="/api/projects/{project_id}/memory", tags=["memory"])
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.get("", response_model=list[MemoryRead])
def list_memory(
    project_id: str,
    session: DatabaseSession,
    type_filter: Annotated[list[MemoryType] | None, Query(alias="type")] = None,
    status_filter: Annotated[list[MemoryStatus] | None, Query(alias="status")] = None,
    visibility: Annotated[list[AiVisibility] | None, Query()] = None,
    pinned: bool | None = None,
    locked: bool | None = None,
    resolved: bool | None = None,
    tag: Annotated[str | None, Query(max_length=40)] = None,
    task: Annotated[str | None, Query(max_length=64)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    sort: MemorySort = "priority",
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MemoryRead]:
    return MemoryService(session).list(
        project_id,
        types=type_filter,
        statuses=status_filter,
        visibility=visibility,
        pinned=pinned,
        locked_only=locked,
        resolved=resolved,
        tag=tag,
        task=task,
        q=q,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
def create_memory(project_id: str, payload: MemoryCreate, session: DatabaseSession) -> MemoryRead:
    created = MemoryService(session).create(project_id, payload)
    if discover_quietly(session, project_id, f"memory:{created.id}")["mentions"]:
        return MemoryService(session).read(project_id, created.id)
    return created


@router.get("/counts", response_model=MemoryCounts)
def memory_counts(project_id: str, session: DatabaseSession) -> MemoryCounts:
    return MemoryService(session).counts(project_id)


@router.get("/{ref}", response_model=MemoryRead)
def get_memory(project_id: str, ref: str, session: DatabaseSession) -> MemoryRead:
    return MemoryService(session).read(project_id, ref)


@router.get("/{ref}/history", response_model=MemoryHistory)
def memory_history(project_id: str, ref: str, session: DatabaseSession) -> MemoryHistory:
    return MemoryService(session).history(project_id, ref)


@router.patch("/{ref}", response_model=MemoryRead)
def update_memory(
    project_id: str, ref: str, payload: MemoryUpdate, session: DatabaseSession
) -> MemoryRead:
    updated = MemoryService(session).update(project_id, ref, payload)
    if {"title", "content"} & payload.model_fields_set:
        discover_quietly(session, project_id, f"memory:{updated.id}")
    return updated


@router.post("/{ref}/supersede", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
def supersede_memory(
    project_id: str, ref: str, payload: MemorySupersede, session: DatabaseSession
) -> MemoryRead:
    created = MemoryService(session).supersede(project_id, ref, payload)
    discover_quietly(session, project_id, f"memory:{created.id}")
    return created


@router.post("/{ref}/links", response_model=MemoryRead)
def link_memory(
    project_id: str, ref: str, payload: MemoryLinkCreate, session: DatabaseSession
) -> MemoryRead:
    return MemoryService(session).link(project_id, ref, payload.related)


@router.delete("/{ref}/links/{related}", response_model=MemoryRead)
def unlink_memory(project_id: str, ref: str, related: str, session: DatabaseSession) -> MemoryRead:
    return MemoryService(session).unlink(project_id, ref, related)


@router.post("/{ref}/invalidate", response_model=MemoryRead)
def invalidate_memory(project_id: str, ref: str, session: DatabaseSession) -> MemoryRead:
    return MemoryService(session).invalidate(project_id, ref)


@router.post("/{ref}/archive", response_model=MemoryRead)
def archive_memory(project_id: str, ref: str, session: DatabaseSession) -> MemoryRead:
    return MemoryService(session).archive(project_id, ref)


@router.post("/{ref}/restore", response_model=MemoryRead)
def restore_memory(project_id: str, ref: str, session: DatabaseSession) -> MemoryRead:
    return MemoryService(session).restore(project_id, ref)


@router.delete("/{ref}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(project_id: str, ref: str, session: DatabaseSession) -> Response:
    MemoryService(session).delete(project_id, ref)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""Project-scoped checkpoint routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.schemas.checkpoint import CheckpointCreate, CheckpointRead, CheckpointUpdate
from app.services.checkpoints import CheckpointService
from app.services.discovery import discover_checkpoint_quietly

router = APIRouter(prefix="/api/projects/{project_id}/checkpoints", tags=["checkpoints"])
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.get("", response_model=list[CheckpointRead])
def list_checkpoints(
    project_id: str,
    session: DatabaseSession,
    task: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CheckpointRead]:
    return CheckpointService(session).list(project_id, task=task, limit=limit, offset=offset)


@router.post("", response_model=CheckpointRead, status_code=status.HTTP_201_CREATED)
def create_checkpoint(
    project_id: str, payload: CheckpointCreate, session: DatabaseSession
) -> CheckpointRead:
    created = CheckpointService(session).create(project_id, payload)
    discover_checkpoint_quietly(session, project_id, created.id)
    return created


@router.get("/latest", response_model=CheckpointRead)
def latest_checkpoint(
    project_id: str,
    session: DatabaseSession,
    task: Annotated[str | None, Query(max_length=64)] = None,
) -> CheckpointRead:
    return CheckpointService(session).latest(project_id, task=task)


@router.get("/{checkpoint_id}", response_model=CheckpointRead)
def get_checkpoint(project_id: str, checkpoint_id: str, session: DatabaseSession) -> CheckpointRead:
    return CheckpointService(session).read(project_id, checkpoint_id)


@router.patch("/{checkpoint_id}", response_model=CheckpointRead)
def update_checkpoint(
    project_id: str, checkpoint_id: str, payload: CheckpointUpdate, session: DatabaseSession
) -> CheckpointRead:
    return CheckpointService(session).update(project_id, checkpoint_id, payload)

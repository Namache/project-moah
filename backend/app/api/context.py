from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.schemas.context import ContextPack, DetailLevel
from app.services.context import ContextService
from app.services.handoff import HandoffService

router = APIRouter(prefix="/api/projects/{project_id}", tags=["context"])
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.get("/context", response_model=ContextPack)
def context_pack(
    project_id: str,
    session: DatabaseSession,
    task: Annotated[str | None, Query(max_length=64)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    detail: DetailLevel = "balanced",
    budget: Annotated[int | None, Query(ge=100, le=20000)] = None,
    include: Annotated[list[str] | None, Query(max_length=50)] = None,
    exclude: Annotated[list[str] | None, Query(max_length=50)] = None,
) -> ContextPack:
    """Preview what an agent would receive. ``include`` names manual-only memory."""
    return ContextService(session).build(
        project_id,
        task=task,
        query=q,
        detail=detail,
        budget=budget,
        include=include,
        exclude=exclude,
    )


class HandoffResponse(BaseModel):
    project_id: str
    task: str | None
    text: str
    estimated_tokens: int
    warnings: list[str]


@router.get("/handoff", response_model=HandoffResponse)
def handoff(
    project_id: str,
    session: DatabaseSession,
    task: Annotated[str | None, Query(max_length=64)] = None,
    budget: Annotated[int, Query(ge=300, le=20000)] = 2000,
) -> dict:
    """A copyable note for switching agents or sessions."""
    return HandoffService(session).build(project_id, task=task, budget=budget)

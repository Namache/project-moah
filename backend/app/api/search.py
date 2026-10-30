"""Search routes. The all-projects route is explicit: it is a separate URL, never a default."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.schemas.memory import MemoryStatus, MemoryType
from app.schemas.search import SearchEntityType, SearchResponse
from app.services.search import SearchService

router = APIRouter(prefix="/api", tags=["search"])
DatabaseSession = Annotated[Session, Depends(get_session)]
Q = Annotated[str, Query(max_length=200)]
Entities = Annotated[list[SearchEntityType] | None, Query(alias="entity_type")]
MemoryTypes = Annotated[list[MemoryType] | None, Query(alias="memory_type")]
MemoryStatuses = Annotated[list[MemoryStatus] | None, Query(alias="memory_status")]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=100000)]


@router.get("/projects/{project_id}/search", response_model=SearchResponse)
def search_project(
    project_id: str,
    session: DatabaseSession,
    q: Q = "",
    entity_type: Entities = None,
    memory_type: MemoryTypes = None,
    memory_status: MemoryStatuses = None,
    include_archived: bool = False,
    limit: Limit = 25,
    offset: Offset = 0,
) -> dict:
    return SearchService(session).search(
        q,
        project_id=project_id,
        entity_types=entity_type,
        memory_types=memory_type,
        memory_statuses=memory_status,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )


@router.get("/search", response_model=SearchResponse)
def search_workspace(
    session: DatabaseSession,
    q: Q = "",
    entity_type: Entities = None,
    memory_type: MemoryTypes = None,
    memory_status: MemoryStatuses = None,
    include_archived: bool = False,
    limit: Limit = 25,
    offset: Offset = 0,
) -> dict:
    return SearchService(session).search(
        q,
        entity_types=entity_type,
        memory_types=memory_type,
        memory_statuses=memory_status,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )

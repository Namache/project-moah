from typing import Literal

from pydantic import BaseModel

from app.schemas.memory import MemoryType

SearchEntityType = Literal["project", "task", "memory", "checkpoint", "file"]


class SearchResult(BaseModel):
    entity_type: SearchEntityType
    entity_id: str
    project_id: str
    project_name: str
    human_id: str | None
    title: str
    snippet: str
    status: str
    memory_type: MemoryType | None
    # Higher is a better match. Only comparable within one response.
    score: float
    updated_at: str | None


class SearchResponse(BaseModel):
    items: list[SearchResult]
    total: int
    limit: int
    offset: int

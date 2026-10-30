"""Read-only audit events."""

from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field

from app.schemas.common import UtcModel

ActorType = Literal["human", "codex", "claude", "system"]


class ActivityRead(UtcModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    project_name: str
    task_id: str | None
    event_type: str
    actor_type: ActorType
    actor_name: str | None
    entity_type: str | None
    entity_id: str | None
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime

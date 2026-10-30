from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcModel

ProposalType = Literal[
    "create_memory",
    "update_memory",
    "supersede_memory",
    "complete_task",
    "update_task",
    "add_acceptance_criterion",
    "associate_file",
    "create_bug",
]
ProposalStatus = Literal["pending", "accepted", "rejected"]


class ProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_type: ProposalType
    # The record this is about, as an ID such as DEC-001 or CAMP-037. Not needed for creates.
    target: str | None = Field(default=None, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(default="", max_length=4000)
    agent: str | None = Field(default=None, max_length=120)


class ProposalRead(UtcModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    human_id: str
    agent: str
    proposal_type: ProposalType
    target_entity_type: str | None
    target_entity_id: str | None
    # Readable name of the target, such as "DEC-001 Starting capacity is 6".
    target_label: str | None = None
    target_locked: bool = False
    payload: dict[str, Any]
    snapshot: dict[str, Any] | None
    reason: str
    status: ProposalStatus
    review_note: str | None
    applied_payload: dict[str, Any] | None
    error: str | None
    created_at: datetime
    reviewed_at: datetime | None
    # Short, human-readable lines describing what accepting would change.
    changes: list[str] = Field(default_factory=list)


class ProposalAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # When given, this replaces the agent's payload ("Edit & Accept").
    payload: dict[str, Any] | None = None
    note: str | None = Field(default=None, max_length=2000)


class ProposalReject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=2000)


class AcceptAllResult(BaseModel):
    accepted: list[ProposalRead]
    failed: list[ProposalRead]


class PendingCount(BaseModel):
    total: int
    by_project: dict[str, int]

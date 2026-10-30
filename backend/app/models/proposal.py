"""Phase 9 AI proposals: changes an agent suggests and a person reviews."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.project import utc_now

PROPOSAL_TYPES = (
    "create_memory",
    "update_memory",
    "supersede_memory",
    "complete_task",
    "update_task",
    "add_acceptance_criterion",
    "associate_file",
    "create_bug",
)


class Proposal(Base):
    __tablename__ = "ai_proposals"
    __table_args__ = (
        CheckConstraint(
            "proposal_type IN (" + ", ".join(repr(t) for t in PROPOSAL_TYPES) + ")",
            name="ck_ai_proposals_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected')", name="ck_ai_proposals_status"
        ),
        UniqueConstraint("project_id", "human_id", name="uq_ai_proposals_human_id"),
        Index("ix_ai_proposals_project_status", "project_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    human_id: Mapped[str] = mapped_column(String(24), nullable=False)
    agent: Mapped[str] = mapped_column(String(120), nullable=False)
    proposal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # Internal id of the record the proposal is about, checked to be in the same project.
    target_entity_type: Mapped[str | None] = mapped_column(String(32))
    target_entity_id: Mapped[str | None] = mapped_column(String(36))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # What the target looked like when the proposal was made, so a reviewer sees a clear diff.
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    review_note: Mapped[str | None] = mapped_column(Text)
    # The payload that was actually applied, when the reviewer edited it before accepting.
    applied_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

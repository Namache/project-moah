from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.project import utc_now


class AgentFolder(Base):
    """A folder Claude Code or Codex worked in, and what Project Moah decided for it."""

    __tablename__ = "agent_folders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('created', 'linked', 'suggested', 'ignored')",
            name="ck_agent_folders_status",
        ),
    )

    folder: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="SET NULL")
    )
    claude_sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    codex_sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

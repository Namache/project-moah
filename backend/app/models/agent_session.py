from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.project import utc_now


class AgentSessionEvent(Base):
    """Which agent session (by the agent's own session id, the name of its log) worked on which
    project and task, and when. Written by Claude Code's SessionStart hook (task empty) and by
    the MCP server whenever the session's task changes. Only ids and times, never text."""

    __tablename__ = "agent_session_events"
    __table_args__ = (
        Index("ix_agent_session_events_session", "agent", "session_id"),
        Index("ix_agent_session_events_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent: Mapped[str] = mapped_column(String(16), nullable=False)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="SET NULL")
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="SET NULL")
    )
    # startup, clear, compact or resume (the hook), or task (the MCP server).
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    # Claude Code's process id, so an MCP server started for one session can follow it
    # through /clear, which starts a new session id in the same process.
    agent_pid: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

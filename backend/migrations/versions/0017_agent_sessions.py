"""Remember which agent session worked on which task, so token use matches tasks by session id.

Revision ID: 0017_agent_sessions
Revises: 0016_pack_build
"""

import sqlalchemy as sa
from alembic import op

revision = "0017_agent_sessions"
down_revision = "0016_pack_build"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_session_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("agent", sa.String(16), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("agent_pid", sa.String(16)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_agent_session_events_session", "agent_session_events", ["agent", "session_id"]
    )
    op.create_index("ix_agent_session_events_created", "agent_session_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("agent_session_events")

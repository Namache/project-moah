"""Remember which chat asked a question or sent a report, and whether the person's answer reached
it: the agent's own session id on the review, when Review's answer was handed to that chat, and
the Claude desktop app's id for a chat session.

Revision ID: 0020_review_sessions
Revises: 0019_review_waits
"""

import sqlalchemy as sa
from alembic import op

revision = "0020_review_sessions"
down_revision = "0019_review_waits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("task_reviews") as batch:
        batch.add_column(sa.Column("session_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_task_reviews_session", ["session_id"])
    with op.batch_alter_table("agent_session_events") as batch:
        batch.add_column(sa.Column("app_session", sa.String(80), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_session_events") as batch:
        batch.drop_column("app_session")
    with op.batch_alter_table("task_reviews") as batch:
        # The index goes first: SQLite refuses to drop a column that an index still uses.
        batch.drop_index("ix_task_reviews_session")
        batch.drop_column("delivered_at")
        batch.drop_column("session_id")

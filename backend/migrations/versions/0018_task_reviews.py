"""Reviews of finished work: an agent's account of a task (or its question to the person), the
person's decision, the follow-up tasks made from it, and files.

Revision ID: 0018_task_reviews
Revises: 0017_agent_sessions
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_task_reviews"
down_revision = "0017_agent_sessions"
branch_labels = None
depends_on = None

STATUSES = "'pending', 'accepted', 'rejected', 'answered', 'replaced'"
TYPES = "'image/png', 'image/jpeg', 'image/webp', 'image/gif', 'text/plain'"


def upgrade() -> None:
    op.create_table(
        "task_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("round", sa.Integer, nullable=False),
        sa.Column("agent", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("done", sa.JSON, nullable=False),
        sa.Column("not_done", sa.JSON, nullable=False),
        sa.Column("how_to_check", sa.Text),
        sa.Column("details", sa.Text),
        sa.Column("options", sa.JSON),
        sa.Column("generated", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("comment", sa.Text),
        sa.Column("moved_to", sa.String(20)),
        sa.Column("follow_ups", sa.JSON, nullable=False),
        sa.CheckConstraint(f"status IN ({STATUSES})", name="ck_task_reviews_status"),
        sa.CheckConstraint("kind IN ('work', 'question')", name="ck_task_reviews_kind"),
        sa.CheckConstraint("round > 0", name="ck_task_reviews_round"),
        sa.UniqueConstraint("task_id", "round", name="uq_task_reviews_task_round"),
    )
    op.create_index("ix_task_reviews_status_created", "task_reviews", ["status", "created_at"])
    op.create_index("ix_task_reviews_project_status", "task_reviews", ["project_id", "status"])
    op.create_index("ix_task_reviews_reviewed", "task_reviews", ["reviewed_at"])
    op.create_table(
        "review_files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "review_id",
            sa.String(36),
            sa.ForeignKey("task_reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("media_type", sa.String(16), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("width", sa.Integer),
        sa.Column("height", sa.Integer),
        sa.Column("caption", sa.Text),
        sa.Column("sort_order", sa.Integer, nullable=False),
        sa.Column("data", sa.LargeBinary, nullable=False),
        sa.Column("created_by", sa.String(120)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('screenshot', 'feedback')", name="ck_review_files_kind"),
        sa.CheckConstraint(f"media_type IN ({TYPES})", name="ck_review_files_media_type"),
        sa.CheckConstraint(
            f"size_bytes BETWEEN 1 AND {5 * 1024 * 1024}", name="ck_review_files_size"
        ),
    )
    op.create_index("ix_review_files_review", "review_files", ["review_id", "kind", "sort_order"])


def downgrade() -> None:
    op.drop_table("review_files")
    op.drop_table("task_reviews")

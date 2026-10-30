"""Add AI proposals awaiting human review.

Revision ID: 0007_proposals
Revises: 0006_files_git
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_proposals"
down_revision = "0006_files_git"
branch_labels = None
depends_on = None

TYPES = (
    "create_memory",
    "update_memory",
    "supersede_memory",
    "complete_task",
    "update_task",
    "add_acceptance_criterion",
    "associate_file",
    "create_bug",
)


def upgrade() -> None:
    op.create_table(
        "ai_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("human_id", sa.String(24), nullable=False),
        sa.Column("agent", sa.String(120), nullable=False),
        sa.Column("proposal_type", sa.String(32), nullable=False),
        sa.Column("target_entity_type", sa.String(32), nullable=True),
        sa.Column("target_entity_id", sa.String(36), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("applied_payload", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "proposal_type IN (" + ", ".join(repr(t) for t in TYPES) + ")",
            name="ck_ai_proposals_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected')", name="ck_ai_proposals_status"
        ),
        sa.UniqueConstraint("project_id", "human_id", name="uq_ai_proposals_human_id"),
    )
    op.create_index(
        "ix_ai_proposals_project_status", "ai_proposals", ["project_id", "status", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("ai_proposals")

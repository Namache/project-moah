"""Remember the folders Claude Code and Codex have worked in, and what was decided for each.

Revision ID: 0009_agent_folders
Revises: 0008_global_links
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_agent_folders"
down_revision = "0008_global_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_folders",
        sa.Column("folder", sa.Text(), primary_key=True),
        # created: a project was made for it. linked: a person matched it to an existing project.
        # suggested: waiting for a person to confirm a likely match. ignored: never sync it.
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("claude_sessions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("codex_sessions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('created', 'linked', 'suggested', 'ignored')",
            name="ck_agent_folders_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("agent_folders")

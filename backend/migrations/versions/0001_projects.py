"""Create the project registry.

Revision ID: 0001_projects
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_projects"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("name_key", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(length=40), nullable=True),
        sa.Column("accent", sa.String(length=40), nullable=True),
        sa.Column("root_path", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("current_focus_task_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'completed', 'archived')",
            name="ck_projects_status",
        ),
        sa.UniqueConstraint("name_key", name="uq_projects_name_key"),
        sa.UniqueConstraint("slug", name="uq_projects_slug"),
    )


def downgrade() -> None:
    op.drop_table("projects")

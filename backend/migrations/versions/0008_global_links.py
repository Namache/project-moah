"""Add the Global scope for rules shared by every project, and links between memories.

The Global scope is a reserved project row (kind 'global'), so its rules and memory reuse every
existing table, rule and screen. It never appears in project lists.

Revision ID: 0008_global_links
Revises: 0007_proposals
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0008_global_links"
down_revision = "0007_proposals"
branch_labels = None
depends_on = None

GLOBAL_ID = "global"


def upgrade() -> None:
    # Added in place, not by rebuilding the table, so no row that refers to a project is touched.
    op.execute(
        "ALTER TABLE projects ADD COLUMN kind VARCHAR(16) NOT NULL DEFAULT 'project'"
        " CONSTRAINT ck_projects_kind CHECK (kind IN ('project', 'global'))"
    )
    now = datetime.now(UTC)
    op.execute(
        sa.text(
            "INSERT INTO projects (id, name, name_key, slug, description, icon, status, kind,"
            " task_prefix, created_at, updated_at) VALUES (:id, 'Global', '__global__',"
            " '__global__', :description, '🌐', 'active', 'global', 'GLB', :now, :now)"
        ).bindparams(
            id=GLOBAL_ID,
            description="Rules and memory that apply to every project.",
            now=now,
        )
    )

    op.create_table(
        "memory_links",
        sa.Column("memory_id", sa.String(36), primary_key=True),
        sa.Column("related_id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("created_by", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["memory_id", "project_id"],
            ["memories.id", "memories.project_id"],
            ondelete="CASCADE",
            name="fk_memory_links_memory_same_project",
        ),
        sa.ForeignKeyConstraint(
            ["related_id", "project_id"],
            ["memories.id", "memories.project_id"],
            ondelete="CASCADE",
            name="fk_memory_links_related_same_project",
        ),
        # Stored once per pair, in a fixed order, so a link has no direction.
        sa.CheckConstraint("memory_id < related_id", name="ck_memory_links_ordered"),
    )
    op.create_index("ix_memory_links_related", "memory_links", ["related_id"])


def downgrade() -> None:
    op.drop_table("memory_links")
    # Removing the Global scope removes its rules and memory with it. Migrations run without
    # foreign-key enforcement, so every table that carries project_id is cleared explicitly.
    bind = op.get_bind()
    tables = bind.execute(
        sa.text("SELECT name FROM sqlite_master WHERE type = 'table' AND name <> 'projects'")
    ).scalars()
    for table in list(tables):
        columns = {row[1] for row in bind.execute(sa.text(f'PRAGMA table_info("{table}")'))}
        if "project_id" in columns:
            bind.execute(
                sa.text(f'DELETE FROM "{table}" WHERE project_id = :id').bindparams(id=GLOBAL_ID)
            )
    op.execute(sa.text("DELETE FROM projects WHERE id = :id").bindparams(id=GLOBAL_ID))
    op.execute("ALTER TABLE projects DROP COLUMN kind")

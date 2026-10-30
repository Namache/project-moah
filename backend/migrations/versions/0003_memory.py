"""Add durable project memory.

Revision ID: 0003_memory
Revises: 0002_tasks
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_memory"
down_revision = "0002_tasks"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "memories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("human_id", sa.String(24), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("importance", sa.String(16), nullable=False),
        sa.Column("is_pinned", sa.Boolean(), nullable=False),
        sa.Column("is_locked", sa.Boolean(), nullable=False),
        sa.Column("ai_visibility", sa.String(16), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=True),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("supersedes_id", sa.String(36), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("invalidated_at", TS, nullable=True),
        sa.Column("archived_at", TS, nullable=True),
        sa.CheckConstraint(
            "type IN ('decision', 'rule', 'fact', 'idea', 'bug', 'note', 'warning')",
            name="ck_memories_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'superseded', 'invalidated', 'archived')",
            name="ck_memories_status",
        ),
        sa.CheckConstraint(
            "importance IN ('low', 'normal', 'high', 'critical')", name="ck_memories_importance"
        ),
        sa.CheckConstraint(
            "ai_visibility IN ('always', 'relevant_only', 'manual_only', 'hidden')",
            name="ck_memories_visibility",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_memories_confidence",
        ),
        sa.CheckConstraint("supersedes_id IS NULL OR supersedes_id <> id", name="ck_memories_self"),
        sa.UniqueConstraint("project_id", "human_id", name="uq_memories_project_human_id"),
        sa.UniqueConstraint("id", "project_id", name="uq_memories_id_project"),
        sa.UniqueConstraint("supersedes_id", name="uq_memories_one_successor"),
        sa.ForeignKeyConstraint(
            ["supersedes_id", "project_id"],
            ["memories.id", "memories.project_id"],
            name="fk_memories_supersedes_same_project",
        ),
    )
    op.create_index("ix_memories_project_type_status", "memories", ["project_id", "type", "status"])
    op.create_index(
        "ix_memories_project_status_updated", "memories", ["project_id", "status", "updated_at"]
    )

    op.create_table(
        "memory_tags",
        sa.Column("memory_id", sa.String(36), primary_key=True),
        sa.Column("tag_id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(
            ["memory_id", "project_id"],
            ["memories.id", "memories.project_id"],
            ondelete="CASCADE",
            name="fk_memory_tags_memory_same_project",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id", "project_id"],
            ["tags.id", "tags.project_id"],
            ondelete="CASCADE",
            name="fk_memory_tags_tag_same_project",
        ),
    )
    op.create_index("ix_memory_tags_tag", "memory_tags", ["tag_id"])

    op.create_table(
        "memory_tasks",
        sa.Column("memory_id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(
            ["memory_id", "project_id"],
            ["memories.id", "memories.project_id"],
            ondelete="CASCADE",
            name="fk_memory_tasks_memory_same_project",
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "project_id"],
            ["tasks.id", "tasks.project_id"],
            ondelete="CASCADE",
            name="fk_memory_tasks_task_same_project",
        ),
    )
    op.create_index("ix_memory_tasks_task", "memory_tasks", ["task_id"])


def downgrade() -> None:
    op.drop_table("memory_tasks")
    op.drop_table("memory_tags")
    op.drop_table("memories")

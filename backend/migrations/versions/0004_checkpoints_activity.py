"""Add project checkpoints and an append-only activity timeline.

Revision ID: 0004_checkpoints_activity
Revises: 0003_memory
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_checkpoints_activity"
down_revision = "0003_memory"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
TASK_PROJECT_CHECK = (
    "(task_id IS NULL AND task_project_id IS NULL) OR "
    "(task_id IS NOT NULL AND task_project_id IS NOT NULL AND task_project_id = project_id)"
)


def upgrade() -> None:
    op.create_table(
        "checkpoints",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_id", sa.String(36), nullable=True),
        sa.Column("task_project_id", sa.String(36), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("completed_work", sa.Text(), nullable=False),
        sa.Column("remaining_work", sa.Text(), nullable=False),
        sa.Column("problems", sa.Text(), nullable=False),
        sa.Column("next_steps", sa.Text(), nullable=False),
        sa.Column("agent", sa.String(120), nullable=True),
        sa.Column("git_commit", sa.String(64), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.UniqueConstraint("id", "project_id", name="uq_checkpoints_id_project"),
        sa.ForeignKeyConstraint(
            ["task_id", "task_project_id"],
            ["tasks.id", "tasks.project_id"],
            ondelete="SET NULL",
            name="fk_checkpoints_task_same_project",
        ),
        sa.CheckConstraint(TASK_PROJECT_CHECK, name="ck_checkpoints_task_project"),
    )
    op.create_index(
        "ix_checkpoints_project_created", "checkpoints", ["project_id", "created_at", "id"]
    )
    op.create_index("ix_checkpoints_task_created", "checkpoints", ["task_id", "created_at", "id"])

    op.create_table(
        "activity_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_id", sa.String(36), nullable=True),
        sa.Column("task_project_id", sa.String(36), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_name", sa.String(120), nullable=True),
        sa.Column("entity_type", sa.String(32), nullable=True),
        sa.Column("entity_id", sa.String(64), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("timestamp", TS, nullable=False),
        sa.CheckConstraint(
            "actor_type IN ('human', 'codex', 'claude', 'system')",
            name="ck_activity_actor_type",
        ),
        sa.CheckConstraint(TASK_PROJECT_CHECK, name="ck_activity_task_project"),
        sa.ForeignKeyConstraint(
            ["task_id", "task_project_id"],
            ["tasks.id", "tasks.project_id"],
            ondelete="SET NULL",
            name="fk_activity_task_same_project",
        ),
    )
    op.create_index(
        "ix_activity_project_timestamp", "activity_events", ["project_id", "timestamp", "id"]
    )
    op.create_index("ix_activity_timestamp", "activity_events", ["timestamp", "id"])
    op.create_index("ix_activity_task_timestamp", "activity_events", ["task_id", "timestamp", "id"])


def downgrade() -> None:
    op.drop_table("activity_events")
    op.drop_table("checkpoints")

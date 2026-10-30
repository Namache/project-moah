"""Images attached to tasks and memory records.

Revision ID: 0015_images
Revises: 0014_brain_upkeep
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_images"
down_revision = "0014_brain_upkeep"
branch_labels = None
depends_on = None

BUMP = "UPDATE graph_state SET version = version + 1"


def upgrade() -> None:
    op.create_table(
        "images",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="CASCADE")),
        sa.Column("memory_id", sa.String(36), sa.ForeignKey("memories.id", ondelete="CASCADE")),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("media_type", sa.String(16), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("width", sa.Integer),
        sa.Column("height", sa.Integer),
        sa.Column("data", sa.LargeBinary, nullable=False),
        sa.Column("created_by", sa.String(120)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("(task_id IS NULL) <> (memory_id IS NULL)", name="ck_images_one_owner"),
        sa.CheckConstraint(
            "media_type IN ('image/png', 'image/jpeg', 'image/webp', 'image/gif')",
            name="ck_images_media_type",
        ),
        sa.CheckConstraint("size_bytes BETWEEN 1 AND 5242880", name="ck_images_size"),
    )
    op.create_index("ix_images_task", "images", ["task_id"])
    op.create_index("ix_images_memory", "images", ["memory_id"])
    # Packs mention a record's images, so a cached pack must not outlive a change to them.
    for event in ("INSERT", "UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER trg_images_version_{event.lower()} AFTER {event} ON images "
            f"BEGIN {BUMP}; END"
        )


def downgrade() -> None:
    for event in ("insert", "update", "delete"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_images_version_{event}")
    op.drop_table("images")

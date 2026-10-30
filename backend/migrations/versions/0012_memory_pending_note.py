"""A short note on why a known issue is still pending after review.

Revision ID: 0012_memory_pending_note
Revises: 0011_memory_resolved
"""

from alembic import op

revision = "0012_memory_pending_note"
down_revision = "0011_memory_resolved"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE memories ADD COLUMN pending_note TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE memories DROP COLUMN pending_note")

"""Known issues can be pending or resolved.

Revision ID: 0011_memory_resolved
Revises: 0010_app_settings
"""

from alembic import op

revision = "0011_memory_resolved"
down_revision = "0010_app_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Plain ALTER TABLE: batch mode would rebuild memories, which other tables point at.
    op.execute("ALTER TABLE memories ADD COLUMN is_resolved BOOLEAN NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE memories DROP COLUMN is_resolved")

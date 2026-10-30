"""App-wide settings that the MCP server must also see, such as the second-opinion switch.

Revision ID: 0010_app_settings
Revises: 0009_agent_folders
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_app_settings"
down_revision = "0009_agent_folders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_settings")

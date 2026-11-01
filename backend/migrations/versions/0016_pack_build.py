"""Record which Project Moah build served each context pack.

Revision ID: 0016_pack_build
Revises: 0015_images
"""

import sqlalchemy as sa
from alembic import op

revision = "0016_pack_build"
down_revision = "0015_images"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("retrieval_sessions") as batch:
        batch.add_column(sa.Column("build", sa.String(80), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("retrieval_sessions") as batch:
        batch.drop_column("build")

"""Remember which checkpoint opened a question round: an agent's note that waits for the person
becomes a question in Review, kept up to date by its later notes and settled when it moves on.

Revision ID: 0019_review_waits
Revises: 0018_task_reviews
"""

import sqlalchemy as sa
from alembic import op

revision = "0019_review_waits"
down_revision = "0018_task_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("task_reviews") as batch:
        batch.add_column(sa.Column("checkpoint_id", sa.String(36), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("task_reviews") as batch:
        batch.drop_column("checkpoint_id")

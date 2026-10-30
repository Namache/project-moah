"""Link System Phase 3: graph version for the path cache, record usefulness, pack sizes.

Revision ID: 0014_brain_upkeep
Revises: 0013_link_system
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_brain_upkeep"
down_revision = "0013_link_system"
branch_labels = None
depends_on = None

# Every table whose rows can change what a context pack finds. Any insert, update or delete in
# one of them bumps graph_state.version, so a cached path is never served after the knowledge
# behind it changed, whichever process (the app or the MCP server) made the change.
# A new table that holds knowledge must be added here in its own migration;
# tests/test_upkeep.py fails until it is.
VERSIONED_TABLES = (
    "projects",
    "milestones",
    "tasks",
    "task_acceptance_criteria",
    "task_relationships",
    "tags",
    "task_tags",
    "memories",
    "memory_tags",
    "memory_tasks",
    "memory_links",
    "checkpoints",
    "project_files",
    "file_symbols",
    "file_tasks",
    "file_memories",
    "file_checkpoints",
    "git_commits",
    "commit_tasks",
    "commit_files",
    "shelves",
    "shelf_members",
    "node_usefulness",
)
# data_links also counts uses of a link; recording a pack must not invalidate the cache, so
# only changes to what a link means bump the version.
DATA_LINK_COLUMNS = (
    "source_kind, source_id, target_kind, target_id, relationship, strength, confidence, "
    "status, contextual_weights, project_id"
)
BUMP = "UPDATE graph_state SET version = version + 1"


def upgrade() -> None:
    op.create_table(
        "graph_state",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.CheckConstraint("id = 1", name="ck_graph_state_single_row"),
    )
    op.execute("INSERT INTO graph_state (id, version) VALUES (1, 0)")

    # How often a record helped, or was noise, for each kind of work.
    op.create_table(
        "node_usefulness",
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("node_kind", sa.String(16), primary_key=True),
        sa.Column("node_id", sa.String(36), primary_key=True),
        sa.Column("operation", sa.String(20), primary_key=True),
        sa.Column("useful", sa.Integer, nullable=False, server_default="0"),
        sa.Column("not_useful", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column("retrieval_sessions", sa.Column("tokens", sa.Integer, nullable=True))

    for table in VERSIONED_TABLES:
        for event in ("INSERT", "UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER trg_{table}_version_{event.lower()} AFTER {event} ON {table} "
                f"BEGIN {BUMP}; END"
            )
    for event in ("INSERT", "DELETE"):
        op.execute(
            f"CREATE TRIGGER trg_data_links_version_{event.lower()} AFTER {event} ON data_links "
            f"BEGIN {BUMP}; END"
        )
    op.execute(
        f"CREATE TRIGGER trg_data_links_version_update AFTER UPDATE OF {DATA_LINK_COLUMNS} "
        f"ON data_links BEGIN {BUMP}; END"
    )
    # A record's usefulness goes when the record goes, like its links.
    for kind, table in (("task", "tasks"), ("memory", "memories"), ("file", "project_files")):
        op.execute(
            f"CREATE TRIGGER trg_{table}_forget_usefulness AFTER DELETE ON {table} BEGIN "
            f"DELETE FROM node_usefulness WHERE node_kind = '{kind}' AND node_id = OLD.id; END"
        )


def downgrade() -> None:
    for table in ("tasks", "memories", "project_files"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_forget_usefulness")
    for table in (*VERSIONED_TABLES, "data_links"):
        for event in ("insert", "update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_version_{event}")
    with op.batch_alter_table("retrieval_sessions") as batch:
        batch.drop_column("tokens")
    op.drop_table("node_usefulness")
    op.drop_table("graph_state")

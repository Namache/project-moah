"""The Link System: typed data links between existing records, and Specialty Shelves.

Revision ID: 0013_link_system
Revises: 0012_memory_pending_note
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_link_system"
down_revision = "0012_memory_pending_note"
branch_labels = None
depends_on = None

# Node kind -> the table that backs it. Link endpoints are polymorphic, so instead of foreign
# keys a trigger on each table removes links and shelf memberships when a record is deleted.
NODE_TABLES = {
    "task": "tasks",
    "memory": "memories",
    "file": "project_files",
    "checkpoint": "checkpoints",
    "milestone": "milestones",
    "shelf": "shelves",
}

# The relationship vocabulary is checked by the service, not the schema, so it can grow
# without rebuilding the table.
NODE_KINDS = "('task', 'memory', 'file', 'checkpoint', 'milestone', 'shelf')"


def upgrade() -> None:
    op.create_table(
        "data_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_kind", sa.String(16), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("target_kind", sa.String(16), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("relationship", sa.String(40), nullable=False),
        sa.Column("strength", sa.Float, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("created_by", sa.String(16), nullable=False),
        sa.Column("actor", sa.String(120), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("contextual_weights", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("provenance", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("traversal_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reinforced_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"source_kind IN {NODE_KINDS}", name="ck_data_links_source_kind"),
        sa.CheckConstraint(f"target_kind IN {NODE_KINDS}", name="ck_data_links_target_kind"),
        sa.CheckConstraint(
            "created_by IN ('user', 'system', 'inferred', 'imported')",
            name="ck_data_links_created_by",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'weak', 'candidate', 'disputed', 'superseded', 'archived',"
            " 'rejected')",
            name="ck_data_links_status",
        ),
        sa.CheckConstraint("strength >= 0 AND strength <= 1", name="ck_data_links_strength"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_data_links_confidence"),
        sa.CheckConstraint(
            "NOT (source_kind = target_kind AND source_id = target_id)",
            name="ck_data_links_not_self",
        ),
        sa.UniqueConstraint(
            "source_kind",
            "source_id",
            "target_kind",
            "target_id",
            "relationship",
            name="uq_data_links_edge",
        ),
    )
    op.create_index(
        "ix_data_links_source", "data_links", ["project_id", "source_kind", "source_id"]
    )
    op.create_index(
        "ix_data_links_target", "data_links", ["project_id", "target_kind", "target_id"]
    )

    op.create_table(
        "shelves",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("name_key", sa.String(80), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("parent_id", sa.String(36), nullable=True),
        sa.Column("keywords", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "name_key", name="uq_shelves_project_name"),
        sa.UniqueConstraint("id", "project_id", name="uq_shelves_id_project"),
        sa.CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_shelves_not_self"),
        sa.ForeignKeyConstraint(
            ["parent_id", "project_id"],
            ["shelves.id", "shelves.project_id"],
            name="fk_shelves_parent_same_project",
        ),
    )
    op.create_table(
        "shelf_members",
        sa.Column("shelf_id", sa.String(36), primary_key=True),
        sa.Column("node_kind", sa.String(16), primary_key=True),
        sa.Column("node_id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["shelf_id", "project_id"],
            ["shelves.id", "shelves.project_id"],
            ondelete="CASCADE",
            name="fk_shelf_members_shelf_same_project",
        ),
        sa.CheckConstraint(f"node_kind IN {NODE_KINDS}", name="ck_shelf_members_kind"),
    )
    op.create_index("ix_shelf_members_node", "shelf_members", ["node_kind", "node_id"])

    op.create_table(
        "retrieval_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_id", sa.String(36), nullable=True),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("query", sa.Text, nullable=True),
        sa.Column("agent", sa.String(120), nullable=True),
        sa.Column("items", sa.JSON, nullable=False),
        sa.Column("outcome", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_retrieval_sessions_task", "retrieval_sessions", ["project_id", "task_id", "created_at"]
    )

    for kind, table in NODE_TABLES.items():
        op.execute(
            f"CREATE TRIGGER trg_{table}_unlink AFTER DELETE ON {table} BEGIN "
            f"DELETE FROM data_links WHERE (source_kind = '{kind}' AND source_id = OLD.id)"
            f" OR (target_kind = '{kind}' AND target_id = OLD.id); "
            f"DELETE FROM shelf_members WHERE node_kind = '{kind}' AND node_id = OLD.id; "
            "END"
        )


def downgrade() -> None:
    for table in NODE_TABLES.values():
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_unlink")
    op.drop_table("retrieval_sessions")
    op.drop_table("shelf_members")
    op.drop_table("shelves")
    op.drop_table("data_links")

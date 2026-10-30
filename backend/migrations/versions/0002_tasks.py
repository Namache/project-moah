"""Add milestones, tasks, acceptance criteria, relationships, tags, and current focus.

Revision ID: 0002_tasks
Revises: 0001_projects
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_tasks"
down_revision = "0001_projects"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def _projects_table(*, with_phase2: bool) -> sa.Table:
    """Full projects definition, so SQLite batch rebuilds keep every constraint."""
    columns: list[sa.SchemaItem] = [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("name_key", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(40), nullable=True),
        sa.Column("accent", sa.String(40), nullable=True),
        sa.Column("root_path", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("current_focus_task_id", sa.String(36), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("last_opened_at", TS, nullable=True),
        sa.Column("archived_at", TS, nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'completed', 'archived')", name="ck_projects_status"
        ),
        sa.UniqueConstraint("name_key", name="uq_projects_name_key"),
        sa.UniqueConstraint("slug", name="uq_projects_slug"),
    ]
    if with_phase2:
        columns.append(sa.Column("task_prefix", sa.String(12), nullable=True))
        columns.append(
            sa.ForeignKeyConstraint(
                ["current_focus_task_id", "id"],
                ["tasks.id", "tasks.project_id"],
                name="fk_projects_focus_task_same_project",
            )
        )
    return sa.Table("projects", sa.MetaData(), *columns)


def upgrade() -> None:
    # Rebuild projects first, while no table references it yet. SQLite accepts a
    # foreign key to a table that is created later in this migration.
    with op.batch_alter_table(
        "projects", recreate="always", copy_from=_projects_table(with_phase2=False)
    ) as batch:
        batch.add_column(sa.Column("task_prefix", sa.String(12), nullable=True))
        batch.create_foreign_key(
            "fk_projects_focus_task_same_project",
            "tasks",
            ["current_focus_task_id", "id"],
            ["id", "project_id"],
        )

    op.create_table(
        "milestones",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.CheckConstraint(
            "status IN ('planned', 'active', 'completed', 'archived')", name="ck_milestones_status"
        ),
        sa.UniqueConstraint("id", "project_id", name="uq_milestones_id_project"),
    )
    op.create_index("ix_milestones_project_order", "milestones", ["project_id", "sort_order"])

    op.create_table(
        "tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("milestone_id", sa.String(36), nullable=True),
        sa.Column("prefix", sa.String(12), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("human_id", sa.String(24), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("priority", sa.String(16), nullable=False),
        sa.Column("next_action", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("started_at", TS, nullable=True),
        sa.Column("completed_at", TS, nullable=True),
        sa.Column("archived_at", TS, nullable=True),
        sa.CheckConstraint(
            "status IN ('backlog', 'todo', 'in_progress', 'blocked', 'review', 'completed', "
            "'archived')",
            name="ck_tasks_status",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'critical')", name="ck_tasks_priority"
        ),
        sa.CheckConstraint("number > 0", name="ck_tasks_number"),
        sa.UniqueConstraint("project_id", "human_id", name="uq_tasks_project_human_id"),
        sa.UniqueConstraint("id", "project_id", name="uq_tasks_id_project"),
        sa.ForeignKeyConstraint(
            ["milestone_id", "project_id"],
            ["milestones.id", "milestones.project_id"],
            name="fk_tasks_milestone_same_project",
        ),
    )
    op.create_index(
        "ix_tasks_project_status_order", "tasks", ["project_id", "status", "sort_order"]
    )
    op.create_index("ix_tasks_project_prefix_number", "tasks", ["project_id", "prefix", "number"])
    op.create_index("ix_tasks_milestone", "tasks", ["milestone_id"])

    op.create_table(
        "task_acceptance_criteria",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_completed", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_index(
        "ix_task_criteria_task_order", "task_acceptance_criteria", ["task_id", "sort_order"]
    )

    op.create_table(
        "task_relationships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_task_id", sa.String(36), nullable=False),
        sa.Column("target_task_id", sa.String(36), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.CheckConstraint(
            "type IN ('parent', 'depends_on', 'related_to', 'supersedes')",
            name="ck_task_relationships_type",
        ),
        sa.CheckConstraint(
            "source_task_id <> target_task_id", name="ck_task_relationships_not_self"
        ),
        sa.UniqueConstraint(
            "source_task_id", "target_task_id", "type", name="uq_task_relationships_edge"
        ),
        sa.ForeignKeyConstraint(
            ["source_task_id", "project_id"],
            ["tasks.id", "tasks.project_id"],
            ondelete="CASCADE",
            name="fk_task_relationships_source_same_project",
        ),
        sa.ForeignKeyConstraint(
            ["target_task_id", "project_id"],
            ["tasks.id", "tasks.project_id"],
            ondelete="CASCADE",
            name="fk_task_relationships_target_same_project",
        ),
    )
    op.create_index("ix_task_relationships_target", "task_relationships", ["target_task_id"])

    op.create_table(
        "tags",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("name_key", sa.String(40), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.UniqueConstraint("project_id", "name_key", name="uq_tags_project_name"),
        sa.UniqueConstraint("id", "project_id", name="uq_tags_id_project"),
    )

    op.create_table(
        "task_tags",
        sa.Column("task_id", sa.String(36), primary_key=True),
        sa.Column("tag_id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id", "project_id"],
            ["tasks.id", "tasks.project_id"],
            ondelete="CASCADE",
            name="fk_task_tags_task_same_project",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id", "project_id"],
            ["tags.id", "tags.project_id"],
            ondelete="CASCADE",
            name="fk_task_tags_tag_same_project",
        ),
    )
    op.create_index("ix_task_tags_tag", "task_tags", ["tag_id"])


def downgrade() -> None:
    for table in ("task_tags", "tags", "task_relationships", "task_acceptance_criteria"):
        op.drop_table(table)
    op.drop_table("tasks")
    op.drop_table("milestones")
    with op.batch_alter_table(
        "projects", recreate="always", copy_from=_projects_table(with_phase2=True)
    ) as batch:
        batch.drop_constraint("fk_projects_focus_task_same_project", type_="foreignkey")
        batch.drop_column("task_prefix")

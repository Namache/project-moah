"""Add file knowledge, Git commit metadata, and file search.

Revision ID: 0006_files_git
Revises: 0005_search
"""
# ruff: noqa: E501

import sqlalchemy as sa
from alembic import op

revision = "0006_files_git"
down_revision = "0005_search"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
SEARCH_COLUMNS = (
    "title, human_id, body, entity_type, entity_id, project_id, sub_type, status, updated_at"
)
FILE_SELECT = (
    "SELECT f.path, '', coalesce(f.purpose, '') || ' ' || coalesce(f.summary, '') || ' ' || "
    "coalesce((SELECT group_concat(s.name || ' ' || coalesce(s.summary, ''), ' ') "
    "FROM file_symbols s WHERE s.file_id = f.id), ''), 'file', f.id, f.project_id, f.language, "
    "'indexed', f.updated_at FROM project_files f"
)


def reindex(row: str, column: str) -> str:
    return (
        f"DELETE FROM search_index WHERE entity_type = 'file' AND entity_id = {row}.{column}; "
        f"INSERT INTO search_index ({SEARCH_COLUMNS}) {FILE_SELECT} WHERE f.id = {row}.{column};"
    )


SEARCH_TRIGGERS = {
    "si_files_ai": f"CREATE TRIGGER si_files_ai AFTER INSERT ON project_files BEGIN {reindex('NEW', 'id')} END",
    "si_files_au": (
        "CREATE TRIGGER si_files_au AFTER UPDATE OF path, purpose, summary, language "
        f"ON project_files BEGIN {reindex('NEW', 'id')} END"
    ),
    "si_files_ad": (
        "CREATE TRIGGER si_files_ad AFTER DELETE ON project_files BEGIN "
        "DELETE FROM search_index WHERE entity_type = 'file' AND entity_id = OLD.id; END"
    ),
    "si_symbols_ai": f"CREATE TRIGGER si_symbols_ai AFTER INSERT ON file_symbols BEGIN {reindex('NEW', 'file_id')} END",
    "si_symbols_au": (
        "CREATE TRIGGER si_symbols_au AFTER UPDATE OF name, summary ON file_symbols "
        f"BEGIN {reindex('NEW', 'file_id')} END"
    ),
    "si_symbols_ad": f"CREATE TRIGGER si_symbols_ad AFTER DELETE ON file_symbols BEGIN {reindex('OLD', 'file_id')} END",
}


def _file_link(name: str, other: str, other_table: str) -> None:
    op.create_table(
        name,
        sa.Column("file_id", sa.String(36), primary_key=True),
        sa.Column(other, sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(
            ["file_id", "project_id"],
            ["project_files.id", "project_files.project_id"],
            ondelete="CASCADE",
            name=f"fk_{name}_file_same_project",
        ),
        sa.ForeignKeyConstraint(
            [other, "project_id"],
            [f"{other_table}.id", f"{other_table}.project_id"],
            ondelete="CASCADE",
            name=f"fk_{name}_{other}_same_project",
        ),
    )
    op.create_index(f"ix_{name}_{other}", name, [other])


def upgrade() -> None:
    op.create_table(
        "project_files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("language", sa.String(40), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("last_seen_hash", sa.String(64), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.UniqueConstraint("project_id", "path", name="uq_project_files_path"),
        sa.UniqueConstraint("id", "project_id", name="uq_project_files_id_project"),
    )
    op.create_table(
        "file_symbols",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "file_id",
            sa.String(36),
            sa.ForeignKey("project_files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
    )
    op.create_index("ix_file_symbols_file", "file_symbols", ["file_id"])
    _file_link("file_tasks", "task_id", "tasks")
    _file_link("file_memories", "memory_id", "memories")
    _file_link("file_checkpoints", "checkpoint_id", "checkpoints")

    op.create_table(
        "git_commits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sha", sa.String(64), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("author", sa.String(200), nullable=True),
        sa.Column("committed_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.UniqueConstraint("project_id", "sha", name="uq_git_commits_project_sha"),
        sa.UniqueConstraint("id", "project_id", name="uq_git_commits_id_project"),
    )
    op.create_table(
        "commit_tasks",
        sa.Column("commit_id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("origin", sa.String(40), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.CheckConstraint("status IN ('confirmed', 'suggested')", name="ck_commit_tasks_status"),
        sa.ForeignKeyConstraint(
            ["commit_id", "project_id"],
            ["git_commits.id", "git_commits.project_id"],
            ondelete="CASCADE",
            name="fk_commit_tasks_commit_same_project",
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "project_id"],
            ["tasks.id", "tasks.project_id"],
            ondelete="CASCADE",
            name="fk_commit_tasks_task_same_project",
        ),
    )
    op.create_index("ix_commit_tasks_task", "commit_tasks", ["task_id"])
    op.create_table(
        "commit_files",
        sa.Column("commit_id", sa.String(36), primary_key=True),
        sa.Column("path", sa.String(1024), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(
            ["commit_id", "project_id"],
            ["git_commits.id", "git_commits.project_id"],
            ondelete="CASCADE",
            name="fk_commit_files_commit_same_project",
        ),
    )
    op.create_index("ix_commit_files_path", "commit_files", ["project_id", "path"])
    for sql in SEARCH_TRIGGERS.values():
        op.execute(sql)


def downgrade() -> None:
    for name in SEARCH_TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.execute("DELETE FROM search_index WHERE entity_type = 'file'")
    for table in (
        "commit_files",
        "commit_tasks",
        "git_commits",
        "file_checkpoints",
        "file_memories",
        "file_tasks",
        "file_symbols",
        "project_files",
    ):
        op.drop_table(table)

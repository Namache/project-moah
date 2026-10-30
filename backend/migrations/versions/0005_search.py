"""Add the FTS5 search index, kept current by triggers.

Revision ID: 0005_search
Revises: 0004_checkpoints_activity

One row per searchable record. Triggers, not application code, keep the index in step,
so raw SQL, cascades, and every future writer stay covered. Columns after ``body`` are
UNINDEXED filters carried alongside each hit.
"""
# ruff: noqa: E501  (long lines here are SQL)

from alembic import op

revision = "0005_search"
down_revision = "0004_checkpoints_activity"
branch_labels = None
depends_on = None

COLUMNS = "title, human_id, body, entity_type, entity_id, project_id, sub_type, status, updated_at"

# Each builder returns a SELECT whose columns match COLUMNS. ``where`` narrows it to the
# record being reindexed, or is empty for the initial backfill.
JOINED_TASK_TEXT = (
    "coalesce(t.description, '') || ' ' || coalesce(t.next_action, '') || ' ' || "
    "coalesce((SELECT group_concat(c.description, ' ') FROM task_acceptance_criteria c "
    "WHERE c.task_id = t.id), '') || ' ' || "
    "coalesce((SELECT group_concat(g.name, ' ') FROM task_tags tt JOIN tags g ON g.id = tt.tag_id "
    "WHERE tt.task_id = t.id), '')"
)
JOINED_MEMORY_TEXT = (
    "m.content || ' ' || coalesce((SELECT group_concat(g.name, ' ') FROM memory_tags mt "
    "JOIN tags g ON g.id = mt.tag_id WHERE mt.memory_id = m.id), '')"
)


def select_for(entity: str, where: str) -> str:
    clause = f" WHERE {where}" if where else ""
    if entity == "project":
        return (
            "SELECT p.name, p.slug, coalesce(p.description, ''), 'project', p.id, p.id, NULL, "
            f"p.status, p.updated_at FROM projects p{clause}"
        )
    if entity == "task":
        return (
            f"SELECT t.title, t.human_id, {JOINED_TASK_TEXT}, 'task', t.id, t.project_id, NULL, "
            f"t.status, t.updated_at FROM tasks t{clause}"
        )
    if entity == "memory":
        return (
            f"SELECT m.title, m.human_id, {JOINED_MEMORY_TEXT}, 'memory', m.id, m.project_id, "
            f"m.type, m.status, m.updated_at FROM memories m{clause}"
        )
    return (
        "SELECT k.title, '', k.summary || ' ' || k.completed_work || ' ' || k.remaining_work || "
        "' ' || k.problems || ' ' || k.next_steps || ' ' || coalesce(k.agent, ''), 'checkpoint', "
        "k.id, k.project_id, NULL, 'recorded', k.updated_at "
        f"FROM checkpoints k{clause}"
    )


def reindex(entity: str, row: str, id_column: str) -> str:
    """Statements that replace one record's index row. ``row`` is NEW or OLD."""
    key = {"project": "p", "task": "t", "memory": "m", "checkpoint": "k"}[entity]
    return (
        f"DELETE FROM search_index WHERE entity_type = '{entity}' AND entity_id = {row}.{id_column}; "
        f"INSERT INTO search_index ({COLUMNS}) "
        f"{select_for(entity, f'{key}.id = {row}.{id_column}')};"
    )


def remove(entity: str, row: str) -> str:
    return f"DELETE FROM search_index WHERE entity_type = '{entity}' AND entity_id = {row}.id;"


def trigger(name: str, event: str, table: str, body: str) -> str:
    on = "" if " ON " in event else f" ON {table}"
    return f"CREATE TRIGGER {name} AFTER {event}{on} BEGIN {body} END"


TRIGGERS: list[tuple[str, str]] = []


def add(name: str, event: str, table: str, body: str) -> None:
    TRIGGERS.append((name, trigger(name, event, table, body)))


# Updates only fire for columns that change searchable text, so board renumbering and
# other bookkeeping writes cost nothing.
add("si_projects_ai", "INSERT", "projects", reindex("project", "NEW", "id"))
add(
    "si_projects_au",
    "UPDATE OF name, slug, description, status ON projects",
    "projects",
    reindex("project", "NEW", "id"),
)
add("si_projects_ad", "DELETE", "projects", remove("project", "OLD"))

add("si_tasks_ai", "INSERT", "tasks", reindex("task", "NEW", "id"))
add(
    "si_tasks_au",
    "UPDATE OF title, description, next_action, status, human_id ON tasks",
    "tasks",
    reindex("task", "NEW", "id"),
)
add("si_tasks_ad", "DELETE", "tasks", remove("task", "OLD"))
add("si_criteria_ai", "INSERT", "task_acceptance_criteria", reindex("task", "NEW", "task_id"))
add(
    "si_criteria_au",
    "UPDATE OF description ON task_acceptance_criteria",
    "task_acceptance_criteria",
    reindex("task", "NEW", "task_id"),
)
add("si_criteria_ad", "DELETE", "task_acceptance_criteria", reindex("task", "OLD", "task_id"))
add("si_task_tags_ai", "INSERT", "task_tags", reindex("task", "NEW", "task_id"))
add("si_task_tags_ad", "DELETE", "task_tags", reindex("task", "OLD", "task_id"))

add("si_memories_ai", "INSERT", "memories", reindex("memory", "NEW", "id"))
add(
    "si_memories_au",
    "UPDATE OF title, content, status, human_id, type ON memories",
    "memories",
    reindex("memory", "NEW", "id"),
)
add("si_memories_ad", "DELETE", "memories", remove("memory", "OLD"))
add("si_memory_tags_ai", "INSERT", "memory_tags", reindex("memory", "NEW", "memory_id"))
add("si_memory_tags_ad", "DELETE", "memory_tags", reindex("memory", "OLD", "memory_id"))

add("si_checkpoints_ai", "INSERT", "checkpoints", reindex("checkpoint", "NEW", "id"))
add(
    "si_checkpoints_au",
    "UPDATE OF title, summary, completed_work, remaining_work, problems, next_steps, agent "
    "ON checkpoints",
    "checkpoints",
    reindex("checkpoint", "NEW", "id"),
)
add("si_checkpoints_ad", "DELETE", "checkpoints", remove("checkpoint", "OLD"))


def upgrade() -> None:
    op.execute(
        "CREATE VIRTUAL TABLE search_index USING fts5("
        "title, human_id, body, "
        "entity_type UNINDEXED, entity_id UNINDEXED, project_id UNINDEXED, "
        "sub_type UNINDEXED, status UNINDEXED, updated_at UNINDEXED, "
        "tokenize = 'unicode61 remove_diacritics 2')"
    )
    for entity in ("project", "task", "memory", "checkpoint"):
        op.execute(f"INSERT INTO search_index ({COLUMNS}) {select_for(entity, '')}")
    for _, sql in TRIGGERS:
        op.execute(sql)


def downgrade() -> None:
    for name, _ in TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.execute("DROP TABLE IF EXISTS search_index")

"""Full-text search over projects, tasks, memory, and checkpoints (SQLite FTS5).

The index is maintained by database triggers (migration ``0005_search``). This module only
reads it. Search results are for people to browse; nothing here feeds agent context.

Ranking, in order:
1. A record whose human ID equals the whole query (``CAMP-037``) comes first.
2. Better BM25 score, with matches in the title weighted 10x and in the ID 8x over the body.
3. Entity order: tasks, memory, checkpoints, projects.
4. Most recently updated, then ID, so equal results never reorder between requests.
"""
# ruff: noqa: E501  (long lines here are SQL)

from __future__ import annotations

import re
from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.memory import MEMORY_STATUSES
from app.services.projects import ProjectService

MAX_TERMS = 12
AGENT_HIDDEN_VISIBILITY = ("hidden", "manual_only")
TERM_PATTERN = re.compile(r"\w+", re.UNICODE)
SNIPPET_TOKENS = 24


# Words too common to say whether a record is related; only dropped when any word may match.
STOPWORDS = frozenset(
    "a an and are as at be but by do for from has have how if in into is it its of on or so"
    " that the their then there these this to was we were what when which while who why will"
    " with without you your add fix make use update set get".split()
)


def without_trailing_tags(snippet: str, tags: Iterable[str]) -> str:
    """Drop the tag names the search index appends to a record's text, so a snippet reads like
    the record ("...counting from now.") instead of ending in its tags ("...from now. saves offline").
    Only a run of tags at the very end goes, and only after a sentence ends or where a cut-off
    snippet's "..." stands, so a sentence that merely ends with a tag's word is kept."""
    names = {word for name in tags for word in name.casefold().split()}
    if not names or not snippet:
        return snippet
    cut = snippet.endswith("...")
    words = (snippet[:-3] if cut else snippet).rstrip().split(" ")
    end = len(words)
    while end > 0 and words[end - 1].casefold() in names:
        end -= 1
    if end == len(words):
        return snippet
    before = " ".join(words[:end]).rstrip()
    if before and not before.endswith((".", "!", "?", ":", ";", ")", "...")):
        return snippet
    # Nothing but tags (a task with no description): no snippet beats repeating the tags.
    return before


def match_expression(query: str, *, any_word: bool = False) -> str | None:
    """Turn free text into a safe FTS5 query: every word required, last word a prefix.

    Each word is double-quoted, so operators and punctuation typed by a person (``-``, ``:``,
    ``"``, ``*``, ``NEAR``) are plain text and can never be a syntax error. ``CAMP-037``
    becomes the two words ``camp`` and ``037``.

    With ``any_word`` a record matching any meaningful word counts (BM25 still ranks records
    that match more words first). This is for finding related records, not for people typing
    a search.
    """
    terms = TERM_PATTERN.findall(query)
    if any_word:
        terms = list(dict.fromkeys(t for t in terms if t.casefold() not in STOPWORDS))
    terms = terms[:MAX_TERMS]
    if not terms:
        return None
    quoted = [f'"{term}"' for term in terms]
    if any_word:
        return " OR ".join(quoted)
    quoted[-1] += "*"
    return " ".join(quoted)


class SearchService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.projects = ProjectService(session)

    def search(
        self,
        query: str,
        *,
        project_id: str | None = None,
        entity_types: Iterable[str] | None = None,
        memory_types: Iterable[str] | None = None,
        memory_statuses: Iterable[str] | None = None,
        include_archived: bool = False,
        for_agent: bool = False,
        any_word: bool = False,
        limit: int = 25,
        offset: int = 0,
    ) -> dict:
        """Search one project, or every project when ``project_id`` is None.

        ``for_agent`` leaves out memory a person has hidden from agents or keeps for manual use.
        """
        if project_id is not None:
            self.projects.get(project_id)  # 404 for an unknown project
        expression = match_expression(query, any_word=any_word)
        if expression is None:
            return {"items": [], "total": 0, "limit": limit, "offset": offset}

        entities = list(dict.fromkeys(entity_types or []))
        memory_types = list(dict.fromkeys(memory_types or []))
        if memory_types and not entities:
            entities = ["memory"]  # a memory type only makes sense for memory
        if not entities:
            entities = ["task", "memory", "checkpoint", "file"] + (
                [] if project_id else ["project"]
            )
        if project_id is not None:
            entities = [e for e in entities if e != "project"]
        if not entities:
            return {"items": [], "total": 0, "limit": limit, "offset": offset}

        statuses = list(dict.fromkeys(memory_statuses or []))
        if not statuses:
            statuses = list(MEMORY_STATUSES) if include_archived else ["active"]

        params: dict[str, object] = {"match": expression, "limit": limit, "offset": offset}
        clauses = ["search_index MATCH :match"]
        if project_id is not None:
            clauses.append("search_index.project_id = :project_id")
            params["project_id"] = project_id
        else:
            clauses.append("(p.status != 'archived' OR :include_archived)")
            params["include_archived"] = include_archived

        # Per-entity visibility rules, OR-ed together for the entities requested.
        branches = []
        for index, entity in enumerate(entities):
            key = f"entity_{index}"
            params[key] = entity
            branch = f"search_index.entity_type = :{key}"
            if entity == "task" and not include_archived:
                branch += " AND search_index.status != 'archived'"
            if entity == "project" and not include_archived:
                branch += " AND search_index.status != 'archived'"
            if entity == "memory":
                branch += f" AND search_index.status IN ({self._bind(statuses, 'ms', params)})"
                if memory_types:
                    branch += (
                        f" AND search_index.sub_type IN ({self._bind(memory_types, 'mt', params)})"
                    )
                if for_agent:
                    hidden = self._bind(list(AGENT_HIDDEN_VISIBILITY), "av", params)
                    branch += (
                        " AND NOT EXISTS (SELECT 1 FROM memories m WHERE m.id = search_index.entity_id"
                        f" AND m.ai_visibility IN ({hidden}))"
                    )
            branches.append(f"({branch})")
        clauses.append("(" + " OR ".join(branches) + ")")

        where = " AND ".join(clauses)
        from_sql = (
            "FROM search_index JOIN projects p ON p.id = search_index.project_id WHERE " + where
        )
        total = self.session.execute(text(f"SELECT count(*) {from_sql}"), params).scalar_one()

        params["exact"] = query.strip().upper()
        rows = (
            self.session.execute(
                text(
                    f"""
                SELECT search_index.entity_type, search_index.entity_id, search_index.project_id, p.name AS project_name,
                       search_index.human_id, search_index.title, search_index.sub_type, search_index.status, search_index.updated_at,
                       snippet(search_index, 2, '', '', '...', {SNIPPET_TOKENS}) AS snip,
                       substr(search_index.body, 1, 200) AS lead,
                       bm25(search_index, 10.0, 8.0, 1.0) AS rank
                {from_sql}
                ORDER BY (upper(search_index.human_id) = :exact AND search_index.human_id != '') DESC,
                         rank ASC,
                         CASE search_index.entity_type WHEN 'task' THEN 0 WHEN 'memory' THEN 1
                              WHEN 'checkpoint' THEN 2 WHEN 'file' THEN 3 ELSE 4 END,
                         search_index.updated_at DESC, search_index.entity_id ASC
                LIMIT :limit OFFSET :offset
                """
                ),
                params,
            )
            .mappings()
            .all()
        )
        tags = self._tags_of(rows)
        items = [
            {
                "entity_type": row["entity_type"],
                "entity_id": row["entity_id"],
                "project_id": row["project_id"],
                "project_name": row["project_name"],
                "human_id": row["human_id"] or None,
                "title": row["title"],
                "snippet": without_trailing_tags(
                    " ".join((row["snip"] or row["lead"] or "").split()),
                    tags.get((row["entity_type"], row["entity_id"]), ()),
                ),
                "status": row["status"],
                "memory_type": row["sub_type"] if row["entity_type"] == "memory" else None,
                "score": round(-float(row["rank"]), 4),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def _tags_of(self, rows: Iterable) -> dict[tuple[str, str], tuple[str, ...]]:
        """The tag names of task and memory results, and the agent name of checkpoints: the index
        appends them to the text, and they are kept out of the snippets."""
        wanted = {"task": set(), "memory": set(), "checkpoint": set()}
        for row in rows:
            if row["entity_type"] in wanted:
                wanted[row["entity_type"]].add(row["entity_id"])
        found: dict[tuple[str, str], list[str]] = {}
        for kind, join_table, column in (
            ("task", "task_tags", "task_id"),
            ("memory", "memory_tags", "memory_id"),
        ):
            ids = sorted(wanted[kind])
            if not ids:
                continue
            marks = ", ".join(f":id{index}" for index in range(len(ids)))
            for owner, name in self.session.execute(
                text(
                    f"SELECT j.{column}, g.name FROM {join_table} j JOIN tags g ON g.id = j.tag_id WHERE j.{column} IN ({marks})"
                ),
                {f"id{index}": value for index, value in enumerate(ids)},
            ):
                found.setdefault((kind, owner), []).append(name)
        if wanted["checkpoint"]:
            ids = sorted(wanted["checkpoint"])
            marks = ", ".join(f":id{index}" for index in range(len(ids)))
            for owner, agent in self.session.execute(
                text(
                    f"SELECT id, agent FROM checkpoints WHERE agent IS NOT NULL AND agent != '' AND id IN ({marks})"
                ),
                {f"id{index}": value for index, value in enumerate(ids)},
            ):
                found.setdefault(("checkpoint", owner), []).append(agent)
        return {key: tuple(names) for key, names in found.items()}

    @staticmethod
    def _bind(values: list[str], prefix: str, params: dict[str, object]) -> str:
        names = []
        for index, value in enumerate(values):
            name = f"{prefix}_{index}"
            params[name] = value
            names.append(f":{name}")
        return ", ".join(names)

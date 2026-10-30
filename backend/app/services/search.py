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
        rows = self.session.execute(
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
        ).mappings()
        items = [
            {
                "entity_type": row["entity_type"],
                "entity_id": row["entity_id"],
                "project_id": row["project_id"],
                "project_name": row["project_name"],
                "human_id": row["human_id"] or None,
                "title": row["title"],
                "snippet": " ".join((row["snip"] or row["lead"] or "").split()),
                "status": row["status"],
                "memory_type": row["sub_type"] if row["entity_type"] == "memory" else None,
                "score": round(-float(row["rank"]), 4),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    @staticmethod
    def _bind(values: list[str], prefix: str, params: dict[str, object]) -> str:
        names = []
        for index, value in enumerate(values):
            name = f"{prefix}_{index}"
            params[name] = value
            names.append(f":{name}")
        return ", ".join(names)

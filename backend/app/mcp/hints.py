"""Hints the MCP server adds to an answer: possible duplicates and near-miss search hits."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.search import SearchService
from app.services.words import STOPWORDS, TERM_PATTERN, title_words

ANY_WORD_NOTE = "any word: no record has every word of the query, so these share some of them"

# A plain question matches many records on one word each: the best few are enough.
ANY_WORD_LIMIT = 5

DUPLICATE_SHARED = 2  # meaningful title words a possible duplicate must share

DUPLICATE_HINT = (
    "If one of these already says it, use brain_update_memory or brain_supersede_memory "
    "instead of keeping two records."
)

TASK_DUPLICATE_HINT = (
    "If one of these is the same work, use it (brain_update_task) instead of keeping two tasks."
)

DONE_TASK_STATUSES = ("completed", "archived")


def same_titles(
    session: Session, title: str, own_id: str, search: dict[str, Any]
) -> list[dict] | None:
    """Up to three search hits other than ``own_id`` whose titles share at least two meaningful
    words with ``title`` (its only one, for a one-word title). Words in a record's body do not
    count: a shared word there says little about the same thing being said twice. None when
    the search fails: the record is saved, and a hint must never fail the write."""
    own = title_words(title)
    if not own:
        return []
    try:
        hits = SearchService(session).search(title, any_word=True, limit=20, **search)
    except Exception:  # noqa: BLE001 - the record is saved; a hint must never fail the write
        session.rollback()
        return None
    return [
        h
        for h in hits["items"]
        if h["entity_id"] != own_id
        and len(own & title_words(h["title"])) >= min(DUPLICATE_SHARED, len(own))
    ]


def possible_duplicate_tasks(session: Session, project_id: str, task_id: str, title: str) -> dict:
    """Up to three unfinished tasks with nearly the same title (see same_titles): every request
    gets a task now, so the same request asked twice must not quietly become two. Empty when
    none match."""
    hits = same_titles(
        session, title, task_id, {"project_id": project_id, "entity_types": ["task"]}
    )
    same = [
        {"id": h["human_id"], "title": h["title"], "status": h["status"]}
        for h in hits or []
        if h["status"] not in DONE_TASK_STATUSES
    ][:3]
    return {"possible_duplicates": same, "duplicates_hint": TASK_DUPLICATE_HINT} if same else {}


def possible_duplicates(
    session: Session, project_id: str, memory_id: str, memory_type: str, title: str
) -> dict:
    """Up to three active records of the same type with nearly the same title (see
    same_titles), so an agent recording an answer can see whether Moah already said it. Empty
    when none match."""
    search = {
        "project_id": project_id,
        "entity_types": ["memory"],
        "memory_types": [memory_type],
        "for_agent": True,
    }
    hits = same_titles(session, title, memory_id, search)
    same = [{"id": h["human_id"], "title": h["title"]} for h in hits or []][:3]
    return {"possible_duplicates": same, "duplicates_hint": DUPLICATE_HINT} if same else {}


NEAR_MISS = "all words but one"


def near_misses(
    search: SearchService, query: str, found: list[dict], options: dict[str, Any], room: int
) -> list[dict]:
    """Records with every meaningful word of the query but one, best first, that ``found``
    does not hold yet. Only for three words or more: of two, one word is too loose a match."""
    terms = list(
        dict.fromkeys(t for t in TERM_PATTERN.findall(query) if t.casefold() not in STOPWORDS)
    )
    if len(terms) < 3 or room <= 0:
        return []
    seen = {(h["entity_type"], h["entity_id"]) for h in found}
    extra: list[dict] = []
    for index in range(len(terms)):
        rest = " ".join(terms[:index] + terms[index + 1 :])
        for hit in search.search(rest, **{**options, "limit": room})["items"]:
            key = (hit["entity_type"], hit["entity_id"])
            if key not in seen:
                seen.add(key)
                extra.append(hit)
    extra.sort(key=lambda h: -h["score"])
    return extra[:room]

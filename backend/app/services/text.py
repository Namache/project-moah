"""Small text and tag helpers shared by the services."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.task import Tag


def name_key(name: str) -> str:
    """The comparison key for names and tags: Unicode-normalized and case-folded."""
    return unicodedata.normalize("NFKC", name).casefold()


def contains_pattern(query: str) -> str:
    """A LIKE pattern (escape ``\\``) matching text that contains ``query``, case-folded.

    Compare it against ``func.casefold(column)``, which the database connection provides,
    so non-ASCII text matches too (SQLite's own ``lower`` only folds ASCII).
    """
    return "%" + re.sub(r"([\\%_])", r"\\\1", query.strip().casefold()) + "%"


def ensure_tags(session: Session, project_id: str, names: list[str]) -> set[str]:
    """The ids of the project's tags with these names, creating any that are missing."""
    wanted: dict[str, str] = {}
    for name in names:
        wanted.setdefault(name_key(name), name)
    existing = {
        tag.name_key: tag
        for tag in session.scalars(
            select(Tag).where(Tag.project_id == project_id, Tag.name_key.in_(wanted))
        )
    }
    now = datetime.now(UTC)
    for key, name in wanted.items():
        if key not in existing:
            tag = Tag(project_id=project_id, name=name, name_key=key, created_at=now)
            session.add(tag)
            existing[key] = tag
    session.flush()
    return {existing[key].id for key in wanted}

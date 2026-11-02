import re
import sqlite3
from pathlib import Path

from sqlalchemy.engine import make_url

from app.core.config import ensure_sqlite_directory
from app.core.resources import resource_path

REVISION = re.compile(r"^(down_revision|revision)\s*(?::[^=]*)?=\s*(.+)$", re.MULTILINE)


def head_revision(versions: Path) -> str | None:
    """The newest checked-in migration, read from the files without loading Alembic. None when
    the files don't name exactly one head (then Alembic decides)."""
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in versions.glob("*.py"):
        found = dict(REVISION.findall(path.read_text(encoding="utf-8")))
        revision = found.get("revision", "").strip().strip("\"'")
        if not revision:
            return None
        revisions.add(revision)
        parents.add(found.get("down_revision", "None").strip().strip("\"'"))
    heads = revisions - parents
    return heads.pop() if len(heads) == 1 else None


def current_revision(database_url: str) -> str | None:
    """The migration a SQLite database file is at, or None when that can't be read cheaply."""
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or url.database in (None, "", ":memory:"):
        return None
    path = Path(url.database)
    if not path.is_file():
        return None
    try:
        connection = sqlite3.connect(path, timeout=5)
        try:
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def upgrade_database(database_url: str) -> None:
    """Apply checked-in migrations; never build production tables from ORM metadata.

    Every agent session starts this (its brief and its MCP server), so a database already at
    the newest migration is recognised without loading Alembic, which takes longer to load
    than the brief takes to build."""
    ensure_sqlite_directory(database_url)
    head = head_revision(resource_path("backend/migrations/versions"))
    if head is not None and current_revision(database_url) == head:
        return
    from alembic import command
    from alembic.config import Config

    config_path = resource_path("backend/alembic.ini")
    config = Config(str(config_path))
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")

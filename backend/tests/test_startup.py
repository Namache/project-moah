"""What every agent session start pays for: the brief hook and the MCP server's start-up."""

import json
import random
import sqlite3
import statistics
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.resources import resource_path
from app.db.migrate import current_revision, head_revision, upgrade_database
from app.db.session import make_engine
from app.services.token_calibration import held_out_medians

BACKEND = Path(__file__).resolve().parents[1]


def loaded_after(code: str, env: dict | None = None) -> dict[str, bool]:
    """Which heavy libraries a fresh Python process has loaded after running ``code``."""
    probe = (
        f"{code}\nimport json, sys\n"
        "print(json.dumps({m: m in sys.modules for m in ('mcp', 'fastapi', 'uvicorn', 'alembic')}))"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    ).stdout
    return json.loads(out.strip().splitlines()[-1])


def test_the_brief_loads_no_mcp_web_or_migration_library() -> None:
    loaded = loaded_after(
        "import app.mcp.cli, app.services.brief, app.services.agent_sync, "
        "app.services.agent_sessions, app.services.context, app.mcp.projects, "
        "app.desktop_server"
    )
    assert loaded == {"mcp": False, "fastapi": False, "uvicorn": False, "alembic": False}


def test_a_current_database_is_opened_without_alembic(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'brain.db'}"
    upgrade_database(url)  # a new file is migrated by Alembic
    head = ScriptDirectory.from_config(Config(str(resource_path("backend/alembic.ini"))))
    assert head_revision(resource_path("backend/migrations/versions")) == head.get_current_head()
    assert current_revision(url) == head.get_current_head()
    loaded = loaded_after(f"from app.db.migrate import upgrade_database\nupgrade_database({url!r})")
    assert loaded["alembic"] is False


def test_an_older_database_is_still_migrated(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'brain.db'}"
    upgrade_database(url)
    engine = make_engine(url)
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '0016_pack_build'"))
        # Everything later migrations add, so the database is as 0016 left it.
        for table in ("review_files", "task_reviews", "agent_session_events"):
            connection.execute(text(f"DROP TABLE {table}"))
    engine.dispose()
    upgrade_database(url)
    assert current_revision(url) == head_revision(resource_path("backend/migrations/versions"))
    engine = make_engine(url)
    with engine.connect() as connection:
        connection.execute(text("SELECT count(*) FROM agent_session_events"))
    engine.dispose()


def test_reviews_and_chat_sessions_gain_their_chat_columns(tmp_path: Path) -> None:
    """Migration 0020 adds the "which chat" columns beside rows that already exist, and takes
    them away again. Going down rebuilds the reviews table, so its files, other indexes and
    constraints must come through that too."""
    path = tmp_path / "chat.db"
    url = f"sqlite:///{path}"
    config = Config(str(resource_path("backend/alembic.ini")))
    config.attributes["database_url"] = url

    def columns(table: str) -> set[str]:
        with closing(sqlite3.connect(path)) as db:
            return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}

    def indexes(table: str) -> set[str]:
        with closing(sqlite3.connect(path)) as db:
            return {row[1] for row in db.execute(f"PRAGMA index_list({table})")}

    command.upgrade(config, "0019_review_waits")
    assert not {"session_id", "delivered_at"} & columns("task_reviews")
    assert "app_session" not in columns("agent_session_events")
    now = "2026-01-01T00:00:00"
    with closing(sqlite3.connect(path)) as db:
        db.execute(
            "INSERT INTO projects (id, name, name_key, slug, status, created_at, updated_at)"
            f" VALUES ('p1', 'Trailhead', 'trailhead', 'trailhead', 'active', '{now}', '{now}')"
        )
        db.execute(
            "INSERT INTO tasks (id, project_id, prefix, number, human_id, title, status, "
            "priority, sort_order, created_at, updated_at) VALUES ('t1', 'p1', 'CAMP', 1, "
            f"'CAMP-001', 'Camp capacity', 'todo', 'normal', 0, '{now}', '{now}')"
        )
        db.execute(
            "INSERT INTO task_reviews (id, project_id, task_id, round, agent, kind, status, "
            "summary, done, not_done, generated, created_at, follow_ups) VALUES ('r1', 'p1', "
            f"'t1', 1, 'claude', 'question', 'pending', 'Six or eight?', '[]', '[]', 0, '{now}', "
            "'[]')"
        )
        db.execute(
            "INSERT INTO review_files (id, project_id, review_id, kind, filename, media_type, "
            "size_bytes, sort_order, data, created_at) VALUES ('f1', 'p1', 'r1', 'screenshot', "
            f"'note.txt', 'text/plain', 1, 0, X'61', '{now}')"
        )
        db.execute(
            "INSERT INTO agent_session_events (agent, session_id, source, created_at) VALUES "
            f"('claude', 'session-aaa', 'prompt', '{now}')"
        )
        db.commit()

    command.upgrade(config, "0020_review_sessions")
    assert {"session_id", "delivered_at"} <= columns("task_reviews")
    assert "app_session" in columns("agent_session_events")
    assert "ix_task_reviews_session" in indexes("task_reviews")
    with closing(sqlite3.connect(path)) as db:  # what was there stays, with the new ones empty
        assert db.execute("SELECT session_id, delivered_at FROM task_reviews").fetchall() == [
            (None, None)
        ]
        assert db.execute("SELECT app_session FROM agent_session_events").fetchall() == [(None,)]

    command.downgrade(config, "0019_review_waits")
    assert not {"session_id", "delivered_at"} & columns("task_reviews")
    assert "app_session" not in columns("agent_session_events")
    assert {
        "ix_task_reviews_status_created",
        "ix_task_reviews_project_status",
        "ix_task_reviews_reviewed",
    } <= indexes("task_reviews")
    assert "ix_task_reviews_session" not in indexes("task_reviews")
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT id FROM task_reviews").fetchall() == [("r1",)]
        assert db.execute("SELECT id FROM review_files").fetchall() == [("f1",)]
        assert db.execute("SELECT session_id FROM agent_session_events").fetchall() == [
            ("session-aaa",)
        ]
        with pytest.raises(sqlite3.IntegrityError):  # the status constraint survived the rebuild
            db.execute("UPDATE task_reviews SET status = 'bogus'")

    command.upgrade(config, "0020_review_sessions")  # and it can go up again
    assert "ix_task_reviews_session" in indexes("task_reviews")


def test_the_database_uses_write_ahead_logging(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'brain.db'}"
    upgrade_database(url)
    engine = make_engine(url)
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode")).scalar() == "wal"
    engine.dispose()


def test_held_out_medians_match_a_median_per_value() -> None:
    rng = random.Random(4)
    for size in (2, 3, 4, 5, 10, 11, 40):
        for _ in range(20):
            values = [rng.choice([rng.random(), 1.0, 2.0]) for _ in range(size)]
            expected = [statistics.median(values[:i] + values[i + 1 :]) for i in range(size)]
            assert held_out_medians(values) == expected

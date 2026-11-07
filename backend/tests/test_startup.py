"""What every agent session start pays for: the brief hook and the MCP server's start-up."""

import json
import random
import statistics
import subprocess
import sys
from pathlib import Path

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

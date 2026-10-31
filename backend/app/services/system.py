"""Local diagnostics and backup. Nothing here leaves the computer or changes project data."""

from __future__ import annotations

import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import get_database_url

APP_VERSION = "0.1.2"
FLATPAK_ID = "io.github.projectbrain.ProjectBrain"
# The .deb puts a small launcher here that starts the bundled backend with --mcp.
DEB_LAUNCHER = Path("/usr/bin/project-moah-mcp")
COUNT_TABLES = {
    "projects": "projects WHERE kind = 'project'",
    "tasks": "tasks",
    "memories": "memories",
    "checkpoints": "checkpoints",
    "files": "project_files",
    "pending_proposals": "ai_proposals WHERE status = 'pending'",
}


def database_path() -> Path | None:
    url = make_url(get_database_url())
    return (
        Path(url.database).resolve()
        if url.drivername.startswith("sqlite") and url.database
        else None
    )


def mcp_tool_count() -> int:
    """How many tools the MCP server registers, counted rather than hard-coded."""
    from sqlalchemy.orm import sessionmaker

    from app.mcp.server import build_server  # imported here: the server imports the services

    return len(build_server(sessionmaker())._tool_manager.list_tools())


def agent_launch() -> dict:
    """How an agent starts this installation's MCP server, so Help shows commands that work."""
    if Path("/.flatpak-info").exists():
        return {
            "install": "flatpak",
            "command": ["flatpak", "run", "--command=project-moah-mcp", FLATPAK_ID],
        }
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            return {"install": "windows", "command": [sys.executable, "--mcp"]}
        if DEB_LAUNCHER.exists():
            return {"install": "deb", "command": [DEB_LAUNCHER.name]}
        return {"install": "linux", "command": [sys.executable, "--mcp"]}
    return {"install": "source", "command": [sys.executable, "-m", "app.mcp.server"]}


def diagnostics(session: Session) -> dict:
    path = database_path()
    migration = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    integrity = session.execute(text("PRAGMA integrity_check")).scalar()
    foreign_key_problems = len(session.execute(text("PRAGMA foreign_key_check")).all())
    try:
        session.execute(text("SELECT count(*) FROM search_index")).scalar()
        fts_ok = True
    except Exception:  # noqa: BLE001 - reported, not raised
        fts_ok = False
    git = shutil.which("git")
    git_version = None
    if git:
        try:
            git_version = (
                subprocess.run(
                    [git, "--version"], capture_output=True, text=True, timeout=5, check=False
                ).stdout.strip()
                or None
            )
        except (OSError, subprocess.TimeoutExpired):
            git_version = None
    return {
        "app_version": APP_VERSION,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "sqlite_version": sqlite3.sqlite_version,
        "database": {
            "path": str(path) if path else None,
            "size_bytes": path.stat().st_size if path and path.exists() else None,
            "migration": migration,
            "integrity": integrity,
            "foreign_key_problems": foreign_key_problems,
            "search_index_ready": fts_ok,
        },
        "counts": {
            name: session.execute(text(f"SELECT count(*) FROM {table}")).scalar()
            for name, table in COUNT_TABLES.items()
        },
        "git": {"available": git is not None, "version": git_version},
        "mcp": {"command": " ".join(agent_launch()["command"]), "tools": mcp_tool_count()},
    }


def export_backup() -> tuple[Path, str]:
    """A consistent copy of the database, made with SQLite's own backup, safe while the app runs."""
    source = database_path()
    if source is None or not source.exists():
        raise FileNotFoundError("The database file could not be found")
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = (
        Path(tempfile.mkdtemp(prefix="project-moah-backup-")) / f"project-moah-backup-{stamp}.db"
    )
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target, target.name

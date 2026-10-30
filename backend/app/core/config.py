"""Resolve the local database location without depending on the shell's cwd."""

import os
import sys
from pathlib import Path

from sqlalchemy.engine import URL, make_url


def get_database_url() -> str:
    """Use an explicit URL, an explicit SQLite path, or the OS user-data directory."""
    if explicit_url := os.getenv("PROJECT_BRAIN_DATABASE_URL"):
        return explicit_url

    if explicit_path := os.getenv("PROJECT_BRAIN_DB_PATH"):
        database_path = Path(explicit_path).expanduser().resolve()
    else:
        if sys.platform == "win32":
            local_app_data = os.getenv("LOCALAPPDATA")
            data_home = (
                Path(local_app_data)
                if local_app_data and Path(local_app_data).is_absolute()
                else Path.home() / "AppData" / "Local"
            )
        else:
            xdg_data_home = os.getenv("XDG_DATA_HOME")
            data_home = (
                Path(xdg_data_home)
                if xdg_data_home and Path(xdg_data_home).is_absolute()
                else Path.home() / ".local" / "share"
            )
        database_path = (data_home / "project-brain" / "project-brain.db").expanduser().resolve()

    return URL.create("sqlite", database=str(database_path)).render_as_string(hide_password=False)


def ensure_sqlite_directory(database_url: str) -> None:
    """Create the parent directory when the configured database is a SQLite file."""
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)

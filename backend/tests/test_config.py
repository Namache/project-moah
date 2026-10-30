import sys
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from app.core.config import get_database_url


@pytest.mark.skipif(sys.platform == "win32", reason="XDG data folders are Linux only")
def test_database_path_uses_user_data_directory_and_overrides(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PROJECT_BRAIN_DATABASE_URL", raising=False)
    monkeypatch.delenv("PROJECT_BRAIN_DB_PATH", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    assert get_database_url() == f"sqlite:///{tmp_path / 'data/project-brain/project-brain.db'}"

    override_path = tmp_path / "alternate.db"
    monkeypatch.setenv("PROJECT_BRAIN_DB_PATH", str(override_path))
    assert get_database_url() == f"sqlite:///{override_path}"

    monkeypatch.setenv("PROJECT_BRAIN_DATABASE_URL", "sqlite:///:memory:")
    assert get_database_url() == "sqlite:///:memory:"

    monkeypatch.delenv("PROJECT_BRAIN_DATABASE_URL")
    unusual_path = tmp_path / "question?mark.db"
    monkeypatch.setenv("PROJECT_BRAIN_DB_PATH", str(unusual_path))
    assert make_url(get_database_url()).database == str(unusual_path)


def test_windows_database_path_uses_local_app_data(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PROJECT_BRAIN_DATABASE_URL", raising=False)
    monkeypatch.delenv("PROJECT_BRAIN_DB_PATH", raising=False)
    monkeypatch.setattr("app.core.config.sys.platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData/Local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "ignored"))

    assert make_url(get_database_url()).database == str(
        tmp_path / "AppData/Local/project-brain/project-brain.db"
    )

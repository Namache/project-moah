"""Agents on an old Moah build are told once to restart, and packs record their build."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.migrate import upgrade_database
from app.db.session import make_engine, make_session_factory
from app.models.app_setting import AppSetting
from app.models.graph import RetrievalSession
from app.services.builds import (
    INSTALLED,
    Build,
    UpdateWatch,
    current_build,
    installed_build,
    pack_builds,
    register_build,
)
from tests.conftest import app_client
from tests.test_mcp import agent, call, seed

pytestmark = pytest.mark.anyio

OLD = Build("0.1.3", 1_000, "aaaaaaa")
NEW = Build("0.1.4", 2_000, "bbbbbbb")


def factory(database_url: str):
    upgrade_database(database_url)
    return make_session_factory(make_engine(database_url))


def test_desktop_app_sets_the_installed_build_and_agents_only_raise_it(database_url: str):
    with factory(database_url)() as session:
        register_build(session, OLD, installed=False)
        assert installed_build(session) == OLD
        register_build(session, NEW, installed=False)
        register_build(session, OLD, installed=False)  # an old session starting is no downgrade
        assert installed_build(session) == NEW
        register_build(session, OLD, installed=True)  # the person really went back
        assert installed_build(session) == OLD


def test_an_old_process_is_told_once(database_url: str):
    with factory(database_url)() as session:
        register_build(session, OLD, installed=True)
        watch = UpdateWatch(OLD)
        assert watch.notice(session) is None
        register_build(session, NEW, installed=True)
        notice = watch.notice(session)
        assert notice and OLD.label in notice and NEW.label in notice and "restart" in notice
        assert watch.notice(session) is None
        # The new build's own processes say nothing.
        assert UpdateWatch(NEW).notice(session) is None


def test_an_executable_replaced_in_place_counts(database_url: str, tmp_path: Path, monkeypatch):
    exe = tmp_path / "project-brain-backend"
    exe.write_text("old")
    monkeypatch.setattr("sys.frozen", True, raising=False)
    with factory(database_url)() as session:
        watch = UpdateWatch(OLD, executable=str(exe))
        assert watch.notice(session) is None
        exe.write_text("new")
        later = datetime.now().timestamp() + 60
        import os

        os.utime(exe, (later, later))
        assert "newer build has been installed" in (watch.notice(session) or "")


def test_old_build_packs_are_counted(database_url: str):
    with factory(database_url)() as session:
        register_build(session, NEW, installed=True)
        row = session.get(AppSetting, INSTALLED)
        row.updated_at = datetime.now(UTC) - timedelta(hours=2)
        session.commit()
        project = session.scalar(select(RetrievalSession.project_id))  # none yet
        assert project is None
        from app.models.project import GLOBAL_PROJECT_ID

        now = datetime.now(UTC)
        for build, age in [
            (NEW.label, 1),
            (OLD.label, 1),
            (None, 1),  # from a build too old to record itself, after the install
            (None, 5),  # before the install: not counted as old
            (OLD.label, 30),  # more than a day ago
        ]:
            session.add(
                RetrievalSession(
                    project_id=GLOBAL_PROJECT_ID,
                    operation="coding",
                    items=[],
                    build=build,
                    created_at=now - timedelta(hours=age),
                )
            )
        session.commit()
        report = pack_builds(session)
        assert report["installed"] == NEW.label
        assert report["old_build_last_day"] == 2
        assert report["last_day"] == {NEW.label: 1, OLD.label: 1, "unknown": 2}


async def test_agents_hear_about_an_update_once_and_packs_record_the_build(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        await seed(client, tmp_path)
    async with agent(database_url) as session:
        error, brief = await call(session, "brain_brief", project="trailhead")
        assert not error and "MOAH WAS UPDATED" not in brief
        # Starting the session noted its build as installed.
        with factory(database_url)() as db:
            assert installed_build(db) == current_build()
            future = Build("9.9.9", current_build().stamp + 3600, "fffffff")
            register_build(db, future, installed=True)
        error, pack = await call(
            session, "brain_context_pack", task="CAMP-001", project="trailhead"
        )
        assert not error and pack.startswith("MOAH WAS UPDATED") and future.label in pack
        error, tasks = await call(session, "brain_get_task", task="CAMP-001", project="trailhead")
        assert not error and "moah_updated" not in tasks
        error, again = await call(
            session, "brain_context_pack", task="CAMP-001", project="trailhead"
        )
        assert not error and "MOAH WAS UPDATED" not in again
    with factory(database_url)() as db:
        builds = db.scalars(select(RetrievalSession.build)).all()
        assert builds and set(builds) == {current_build().label}
        assert pack_builds(db)["old_build_last_day"] == 2  # served by the old session's build

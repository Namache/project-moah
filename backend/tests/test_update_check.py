"""The once-a-day update check: Project Moah tells the agent what is installed, the agent looks."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db.migrate import upgrade_database
from app.db.session import make_engine, make_session_factory
from app.services.settings import AgentSettingsUpdate, update_agent_settings
from app.services.system import APP_VERSION
from app.services.update_check import OFFLINE, take_daily_check
from tests.conftest import app_client
from tests.test_mcp import agent, call, seed

pytestmark = pytest.mark.anyio


def session_for(database_url: str) -> Session:
    upgrade_database(database_url)
    return make_session_factory(make_engine(database_url))()


def test_once_per_day_and_off_switch(database_url: str) -> None:
    with session_for(database_url) as session:
        first = take_daily_check(session, lambda: date(2026, 10, 31))
        assert first and APP_VERSION in first and OFFLINE in first
        assert "Namache/project-moah" in first
        assert take_daily_check(session, lambda: date(2026, 10, 31)) is None
        assert take_daily_check(session, lambda: date(2026, 11, 1))
        update_agent_settings(session, AgentSettingsUpdate(update_check_enabled=False))
        assert take_daily_check(session, lambda: date(2026, 11, 2)) is None
        update_agent_settings(session, AgentSettingsUpdate(update_check_enabled=True))
        assert take_daily_check(session, lambda: date(2026, 11, 2))


async def test_setting_is_on_by_default_and_saved(database_url: str) -> None:
    async with app_client(database_url) as client:
        assert (await client.get("/api/settings/agents")).json()["update_check_enabled"] is True
        changed = await client.patch("/api/settings/agents", json={"update_check_enabled": False})
        assert changed.json()["update_check_enabled"] is False


async def test_first_brief_of_the_day_carries_the_check(database_url: str, tmp_path: Path) -> None:
    async with app_client(database_url) as client:
        await seed(client, tmp_path)
    async with agent(database_url) as session:
        error, brief = await call(session, "brain_brief", project="trailhead")
        assert not error and "UPDATE CHECK" in brief and APP_VERSION in brief
        error, pack = await call(
            session, "brain_context_pack", task="CAMP-001", project="trailhead"
        )
        assert not error and "UPDATE CHECK" not in pack
    async with agent(database_url) as session:  # a second session the same day
        error, brief = await call(session, "brain_brief", project="trailhead")
        assert not error and "UPDATE CHECK" not in brief


async def test_pack_carries_it_when_no_brief_came_first(database_url: str, tmp_path: Path) -> None:
    async with app_client(database_url) as client:
        await seed(client, tmp_path)
    async with agent(database_url) as session:
        error, pack = await call(
            session, "brain_context_pack", task="CAMP-001", project="trailhead"
        )
        assert not error and "UPDATE CHECK" in pack

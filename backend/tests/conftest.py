from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.services import agent_sessions, claude_desktop


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'project-brain.db'}"


@asynccontextmanager
async def app_client(database_url: str) -> AsyncIterator[AsyncClient]:
    application = create_app(database_url)
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://project-brain.test"
        ) as client:
            yield client


@pytest.fixture
async def client(database_url: str) -> AsyncIterator[AsyncClient]:
    async with app_client(database_url) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def no_real_claude_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Review's button looks for the Claude desktop app's records of a chat in the person's own
    config folder. A test must never read it: unless it names its own folders, the app is not
    installed."""
    real = claude_desktop.config_folders

    def folders(environ=None, platform=None, home=None) -> list[Path]:
        if environ is None and platform is None and home is None:
            return [tmp_path / "no-claude-app" / "Claude"]
        return real(environ, platform, home)

    monkeypatch.setattr(claude_desktop, "config_folders", folders)
    agent_sessions.forget_app_misses()

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


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

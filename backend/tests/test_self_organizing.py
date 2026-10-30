"""Shelves keep themselves in order: records file themselves, shelves learn from the work they
helped with, and a crowded shelf asks the agent at work to split it."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import make_engine, make_session_factory
from app.models.checkpoint import ActivityEvent
from app.models.graph import Shelf
from app.models.project import GLOBAL_PROJECT_ID
from app.services import context as context_module
from app.services.context import ContextService
from app.services.graph import Node
from app.services.health import HealthService
from app.services.retrieval import RetrievalService
from app.services.shelves import ShelfService

pytestmark = pytest.mark.anyio


async def post(client: AsyncClient, url: str, **body: object) -> dict:
    response = await client.post(url, json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()


async def memory(client: AsyncClient, pid: str, title: str) -> dict:
    return await post(client, f"/api/projects/{pid}/memory", type="fact", title=title)


async def tree(client: AsyncClient) -> tuple[dict, dict]:
    root = await post(client, "/api/projects/global/shelves", name="Game design")
    leaf = await post(
        client,
        "/api/projects/global/shelves",
        name="Game mechanics",
        parent=root["id"],
        keywords=["combat"],
    )
    return root, leaf


async def test_unfiled_clusters_are_filed_without_anyone_accepting(
    client: AsyncClient, database_url: str
) -> None:
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    combat = [
        await memory(client, pid, f"Combat {name}")
        for name in ("dodge timing", "stamina cost", "hit stop", "enemy telegraph", "parry window")
    ]
    for one, two in zip(combat, combat[1:] + combat[:1], strict=True):
        await post(
            client,
            f"/api/projects/{pid}/links",
            source=one["human_id"],
            relationship="relates_to",
            target=two["human_id"],
            strength=0.7,
        )
    _, leaf = await tree(client)

    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        assert HealthService(session).organize(pid)["place"] == 1
        service = ShelfService(session)
        _, shared = service.shared(pid)
        assert {Node("memory", m["id"]) for m in combat} <= shared[leaf["id"]]
        logged = session.scalars(
            select(ActivityEvent).where(ActivityEvent.actor_name == "moah")
        ).all()
        assert {e.event_type for e in logged} == {"SHELF_MEMBER_ADDED"}
        # Nothing left to do the next day.
        assert not HealthService(session).organize(pid).get("place")


async def test_filing_deeper_takes_a_record_off_the_broader_shelf(
    client: AsyncClient, database_url: str
) -> None:
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    note = await memory(client, pid, "Bosses telegraph their attacks")
    root, leaf = await tree(client)
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        service = ShelfService(session)
        service.place(pid, root["id"], [note["human_id"]])
        service.place(pid, leaf["id"], [note["human_id"]])
        _, shared = service.shared(pid)
        assert Node("memory", note["id"]) in shared[leaf["id"]]
        assert Node("memory", note["id"]) not in shared[root["id"]]


async def test_shelves_learn_the_words_of_work_they_helped(
    client: AsyncClient, database_url: str
) -> None:
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    dodge = await memory(client, pid, "Combat dodge timing")
    await memory(client, pid, "Camp music loop")
    _, leaf = await tree(client)
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        ShelfService(session).place(pid, leaf["id"], [dodge["human_id"]])
        retrieval = RetrievalService(session)
        item = {"kind": "memory", "id": dodge["id"], "label": dodge["title"], "path": []}
        for round_ in range(3):
            pack = retrieval.record(
                pid,
                task_id=None,
                operation="coding",
                query="the stagger feels wrong",
                agent="codex",
                items=[item],
            )
            retrieval.feedback(
                pid, pack.id, useful=[dodge["human_id"]], not_useful=[], actor="codex"
            )
            # Learned only once enough packs agree.
            organized = HealthService(session).organize(pid)
            if round_ < 2:
                assert "stagger" not in (session.get(Shelf, leaf["id"]).keywords or "")
        assert organized["learned_word"] >= 1
        shelf = session.get(Shelf, leaf["id"])
        assert "stagger" in shelf.keywords.split(",")
        pack = ContextService(session).build(pid, query="stagger")
        [woke] = [s for s in pack.shelves if s.name == "Game mechanics"]
        assert woke.active


async def test_a_crowded_shelf_asks_the_agent_to_split_it_once_a_week(
    client: AsyncClient, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(context_module, "CROWDED", 3)
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    notes = [await memory(client, pid, f"Combat note {n}") for n in ("one", "two", "three")]
    _, leaf = await tree(client)
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        ShelfService(session).place(pid, leaf["id"], [n["human_id"] for n in notes])
        first = ContextService(session).build(pid, query="combat")
        asks = [w for w in first.warnings if "split it" in w]
        assert asks and "Game design > Game mechanics" in asks[0]
        again = ContextService(session).build(pid, query="combat")
        assert not [w for w in again.warnings if "split it" in w]
        # Global records do not count toward a project's crowding.
        assert session.get(Shelf, leaf["id"]).project_id == GLOBAL_PROJECT_ID

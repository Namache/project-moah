"""Link System Phase 3: decay, record learning, shelves waking through links, the path cache,
health, clusters and shelf suggestions."""

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.db.session import make_engine, make_session_factory
from app.models.graph import DataLink
from app.models.project import utc_now
from app.services import context as context_module
from app.services.context import ContextService
from app.services.retrieval import RetrievalService
from app.services.upkeep import decay_links, graph_version

pytestmark = pytest.mark.anyio

# Tables that never change what a pack finds, so they need no version trigger.
UNVERSIONED = {
    "activity_events",
    "agent_folders",
    "ai_proposals",
    "alembic_version",
    "app_settings",
    "graph_state",
    "retrieval_sessions",
}


async def post(client: AsyncClient, url: str, **body: object) -> dict:
    response = await client.post(url, json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()


async def memory(client: AsyncClient, pid: str, title: str, kind: str = "fact") -> dict:
    return await post(client, f"/api/projects/{pid}/memory", type=kind, title=title)


async def link(client: AsyncClient, pid: str, a: str, rel: str, b: str, strength: float) -> None:
    await post(
        client,
        f"/api/projects/{pid}/links",
        source=a,
        relationship=rel,
        target=b,
        strength=strength,
    )


async def test_every_knowledge_table_bumps_the_graph_version(
    client: AsyncClient, database_url: str
) -> None:
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        tables = set(
            session.scalars(
                text(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name NOT LIKE 'search_index%' AND name NOT LIKE 'sqlite_%'"
                )
            )
        )
        triggers = set(session.scalars(text("SELECT name FROM sqlite_master WHERE type='trigger'")))
    missing = {t for t in tables - UNVERSIONED if f"trg_{t}_version_insert" not in triggers}
    assert not missing, f"add version triggers for {missing} (see migration 0014)"

    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    task = await post(client, f"/api/projects/{pid}/tasks", title="Fix inventory duplication")
    with factory() as session:
        before = graph_version(session)
        ContextService(session).build(
            pid, task=task["human_id"], record_for="claude", explore=False
        )
        assert graph_version(session) == before  # recording a pack is not a change to knowledge
    await memory(client, pid, "Inventory loads replace state")
    with factory() as session:
        assert graph_version(session) > before


async def test_path_cache_is_reused_until_knowledge_changes(
    client: AsyncClient, database_url: str
) -> None:
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    task = await post(client, f"/api/projects/{pid}/tasks", title="Fix inventory duplication")
    manager = await memory(client, pid, "InventoryManager state")
    await link(client, pid, task["human_id"], "affects", manager["human_id"], 0.7)
    factory = make_session_factory(make_engine(database_url))
    stats = context_module.PATH_CACHE_STATS
    with factory() as session:
        ContextService(session).build(pid, task=task["human_id"])
        hits = stats["hits"]
        ContextService(session).build(pid, task=task["human_id"])
        assert stats["hits"] == hits + 1

    lesson = await memory(client, pid, "Clear runtime state before loading", "rule")
    await link(client, pid, manager["human_id"], "relates_to", lesson["human_id"], 0.9)
    with factory() as session:
        hits = stats["hits"]
        pack = ContextService(session).build(pid, task=task["human_id"])
        assert stats["hits"] == hits  # the new link made the cached walk stale
        assert lesson["title"] in {i.title for i in pack.items}


async def test_idle_links_fade_and_stale_guesses_are_archived(
    client: AsyncClient, database_url: str
) -> None:
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    a = await memory(client, pid, "InventoryManager state")
    b = await memory(client, pid, "Shop pricing table")
    c = await memory(client, pid, "Camp crafting stations")
    await link(client, pid, a["human_id"], "relates_to", b["human_id"], 0.5)
    await link(client, pid, a["human_id"], "relates_to", c["human_id"], 0.5)
    await link(client, pid, b["human_id"], "relates_to", c["human_id"], 0.3)
    factory = make_session_factory(make_engine(database_url))
    old = utc_now() - timedelta(days=100)
    with factory() as session:
        rows = session.scalars(select(DataLink).where(DataLink.project_id == pid)).all()
        rows = sorted(
            (r for r in rows if r.relationship == "relates_to" and r.created_by == "user"),
            key=lambda r: r.strength,
        )
        guess, system, person = rows[0], rows[1], rows[2]
        guess.status, guess.created_by = "candidate", "inferred"
        system.created_by = "system"
        for row in rows:
            row.created_at = old
        session.commit()
        ids = guess.id, system.id, person.id

        now = utc_now()
        assert decay_links(session, now)["ran"] is False  # the first run only starts the clock
        assert decay_links(session, now + timedelta(hours=2))["ran"] is False
        result = decay_links(session, now + timedelta(days=40))
        assert result["ran"] and result["faded"] == 1 and result["archived"] == 1
        guess, system, person = (session.get(DataLink, i) for i in ids)
        assert guess.status == "archived"
        assert 0.4 < system.strength < 0.5  # faded, still followed
        assert system.status == "active"
        assert person.strength == 0.5  # a person's link does not fade


async def test_a_record_that_keeps_being_noise_ranks_lower(
    client: AsyncClient, database_url: str
) -> None:
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    task = await post(client, f"/api/projects/{pid}/tasks", title="Fix inventory duplication")
    noise = await memory(client, pid, "Inventory icons use a 16px grid")
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        retrieval = RetrievalService(session)
        for _ in range(3):
            pack = ContextService(session).build(
                pid, task=task["human_id"], record_for="claude", explore=False
            )
            retrieval.feedback(
                pid, pack.retrieval_id, useful=[], not_useful=[noise["human_id"]], actor="claude"
            )
        factors = retrieval.usefulness(pid, "debugging")
        assert 0.5 <= min(factors.values()) < 0.75
        assert retrieval.usefulness(pid, "design") == {}  # learned for debugging only


async def test_a_shelf_wakes_when_links_from_the_task_reach_it(
    client: AsyncClient, database_url: str
) -> None:
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    base = f"/api/projects/{pid}"
    task = await post(client, f"{base}/tasks", title="Fix item duplication")
    loader = await memory(client, pid, "Inventory loader appends items")
    slots = await memory(client, pid, "SaveManager owns the slots")
    await link(client, pid, task["human_id"], "affects", loader["human_id"], 0.9)
    await link(client, pid, loader["human_id"], "depends_on", slots["human_id"], 0.8)
    shelf = await post(client, f"{base}/shelves", name="Persistence")
    await post(client, f"{base}/shelves/{shelf['id']}/members", node=slots["human_id"])

    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        pack = ContextService(session).build(pid, task=task["human_id"])
    [woke] = [s for s in pack.shelves if s.name == "Persistence"]
    assert woke.active and woke.reason.startswith("linked to the task through")
    assert slots["title"] in {i.title for i in pack.items}


async def test_health_clusters_and_shelf_suggestions(client: AsyncClient) -> None:
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    base = f"/api/projects/{pid}"
    combat = [
        await memory(client, pid, f"Combat {name}")
        for name in ("dodge timing", "stamina cost", "hit stop", "enemy telegraph", "parry window")
    ]
    for one, two in zip(combat, combat[1:] + combat[:1], strict=True):
        await link(client, pid, one["human_id"], "relates_to", two["human_id"], 0.7)
    other = [await memory(client, pid, f"{t}") for t in ("Save slot format", "Camp music loop")]
    await link(client, pid, other[0]["human_id"], "relates_to", other[1]["human_id"], 0.4)

    health = (await client.get(f"{base}/graph/health")).json()
    assert health["nodes"] == 7 and health["links"] >= 6
    assert {"name": "Combat", "size": 5, "trend": None} in health["clusters"], health
    # A cluster no shelf names needs a category; a word from its titles is not one.
    [need] = [s for s in health["suggestions"] if s["kind"] == "needs_category"]
    assert need["size"] == 5 and not [s for s in health["suggestions"] if s["kind"] == "place"]
    response = await client.post(f"{base}/shelf-suggestions/accept", json={"key": need["key"]})
    assert response.status_code == 422

    # With a category in the shared tree that names them, the cluster is offered that shelf.
    root = await post(client, "/api/projects/global/shelves", name="Game design")
    await post(
        client,
        "/api/projects/global/shelves",
        name="Game mechanics",
        parent=root["id"],
        keywords=["combat"],
    )
    health = (await client.get(f"{base}/graph/health")).json()
    [place] = [s for s in health["suggestions"] if s["kind"] == "place"]
    assert place["name"] == "Game design > Game mechanics" and len(place["members"]) == 5
    made = await post(client, f"{base}/shelf-suggestions/accept", key=place["key"])
    assert made["members"] == 5
    assert (await client.get(f"{base}/shelves")).json() == []  # filed, not a new shelf
    health = (await client.get(f"{base}/graph/health")).json()
    assert not [s for s in health["suggestions"] if s["kind"] in ("place", "needs_category")]
    assert health["density"][0] == {
        "shelf_id": made["shelf_id"],
        "name": "Game mechanics",
        "records": 5,
        "connected": 1.0,
    }
    # Another project sees none of these records on the shared shelf.
    elsewhere = (await post(client, "/api/projects", name="Taskbar"))["id"]
    view = (await client.get(f"/api/projects/{elsewhere}/graph")).json()
    assert [s["name"] for s in view["shelves"]] == ["Game design", "Game mechanics"]
    assert not view["nodes"]

    # Two project shelves holding the same records are suggested for merging.
    for name in ("Fighting", "Battle"):
        twin = await post(client, f"{base}/shelves", name=name)
        for m in combat[:4]:
            await post(client, f"{base}/shelves/{twin['id']}/members", node=m["human_id"])
    health = (await client.get(f"{base}/graph/health")).json()
    [merge] = [s for s in health["suggestions"] if s["kind"] == "merge"]
    assert merge["merge_from"]["name"] == "Fighting" and merge["name"] == "Battle"
    merged = await post(client, f"{base}/shelf-suggestions/accept", key=merge["key"])
    assert merged["merged"] == "Fighting"
    assert [s["name"] for s in (await client.get(f"{base}/shelves")).json()] == ["Battle"]

    # Phase 4: the fifth Combat record links mostly to Battle's four, so Battle may take it.
    left = (await client.get(f"{base}/graph/health")).json()["suggestions"]
    [add] = [s for s in left if s["kind"] == "add_member"]
    assert [s["kind"] for s in left] == ["add_member"]
    # Suggestions can be dismissed, and stay dismissed.
    response = await client.post(f"{base}/shelf-suggestions/dismiss", json={"key": add["key"]})
    assert response.status_code == 204
    assert not (await client.get(f"{base}/graph/health")).json()["suggestions"]

    brain = (await client.get("/api/brain/health")).json()
    assert [p["name"] for p in brain["projects"]] == ["Trailhead"]
    assert brain["projects"][0]["retrieval"]["packs"] == 0

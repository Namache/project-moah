"""Link System Phase 4: search-hit feedback, Global routes, predictive retrieval, missing links."""

import pytest
from httpx import AsyncClient

from app.db.session import make_engine, make_session_factory
from app.services.context import ContextService
from app.services.discovery import DiscoveryService
from app.services.retrieval import RetrievalService

pytestmark = pytest.mark.anyio


async def post(client: AsyncClient, url: str, **body: object) -> dict:
    response = await client.post(url, json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()


async def test_useful_search_hit_gets_a_link_from_the_task(
    client: AsyncClient, database_url: str
) -> None:
    """WARN-008: a record that came in by search, with no link path, must still teach."""
    pid = (await post(client, "/api/projects", name="Dragons"))["id"]
    base = f"/api/projects/{pid}"
    task = await post(client, f"{base}/tasks", title="Implement Nest Keeper ranch job")
    dec = await post(
        client, f"{base}/memory", type="decision", title="Nest Keeper ranch job approved"
    )
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        pack = ContextService(session).build(
            pid, task=task["human_id"], record_for="codex", explore=False
        )
        assert dec["title"] in {i.title for i in pack.items}
        result = RetrievalService(session).feedback(
            pid, pack.retrieval_id, useful=[dec["human_id"]], not_useful=[], actor="codex"
        )
    # On-write discovery may already have guessed this link; feedback then confirms it.
    assert result["links_added"] == [dec["human_id"]] or result["links_changed"] >= 1
    links = (await client.get(f"{base}/links", params={"node": task["human_id"]})).json()["links"]
    assert any(x["node"]["label"] == dec["human_id"] and x["status"] == "active" for x in links)


async def test_global_record_travels_only_through_a_route(
    client: AsyncClient, database_url: str
) -> None:
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    other = (await post(client, "/api/projects", name="Starling"))["id"]
    base = f"/api/projects/{pid}"
    task = await post(client, f"{base}/tasks", title="Refactor loot helpers")
    routed = await post(
        client, "/api/projects/global/memory", type="fact", title="Prefer reusable helpers"
    )
    stray = await post(client, "/api/projects/global/memory", type="note", title="Loot helpers")
    secret = await post(
        client, f"/api/projects/{other}/memory", type="decision", title="Loot helpers secret"
    )
    await post(
        client,
        f"{base}/links",
        source=task["human_id"],
        relationship="applies_to",
        target=f"global:{routed['human_id']}",
        strength=0.8,
    )
    bad = await client.post(
        f"{base}/links",
        json={"source": task["human_id"], "relationship": "uses", "target": secret["human_id"]},
    )
    assert bad.status_code >= 400  # another project's record can never be linked
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        pack = ContextService(session).build(pid, task=task["human_id"])
    by_title = {i.title: i for i in pack.items}
    assert by_title[routed["title"]].section == "routed"
    assert "(global)" in by_title[routed["title"]].reason
    assert stray["title"] not in by_title  # a word match alone earns nothing
    assert secret["title"] not in by_title


async def test_records_that_helped_a_similar_task_are_predicted(
    client: AsyncClient, database_url: str
) -> None:
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    base = f"/api/projects/{pid}"
    first = await post(client, f"{base}/tasks", title="Balance camp fire upgrades")
    second = await post(client, f"{base}/tasks", title="Balance camp tent upgrades")
    note = await post(client, f"{base}/memory", type="fact", title="Camp costs live in costs.csv")
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        service = ContextService(session)
        pack = service.build(pid, task=first["human_id"], record_for="claude", explore=False)
        assert note["title"] in {i.title for i in pack.items}
        RetrievalService(session).feedback(
            pid, pack.retrieval_id, useful=[note["human_id"]], not_useful=[], actor="claude"
        )
        predicted = service._predicted(pid, service.tasks.detail(pid, second["human_id"]))
    [(score, why)] = [v for n, v in predicted.items() if n.id == note["id"]]
    assert why == f"helped with similar task {first['human_id']}"
    assert 0.2 < score <= 0.5


async def test_missing_link_between_records_sharing_two_neighbours(
    client: AsyncClient, database_url: str
) -> None:
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    base = f"/api/projects/{pid}"
    a, b, x, y = [
        await post(client, f"{base}/memory", type="fact", title=t)
        for t in ("Alpha system", "Beta panel", "Shared state", "Shared signal")
    ]
    for end in (a, b):
        for mid in (x, y):
            await post(
                client,
                f"{base}/links",
                source=end["human_id"],
                relationship="uses",
                target=mid["human_id"],
                strength=0.8,
            )
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        assert DiscoveryService(session).find_missing(pid)["missing"] >= 1
    cands = (await client.get(f"{base}/links/candidates")).json()
    assert any(
        {c["source"]["label"], c["target"]["label"]} == {a["human_id"], b["human_id"]}
        for c in cands
    )


async def test_same_lesson_in_two_projects_can_be_shared(
    client: AsyncClient, database_url: str
) -> None:
    a = (await post(client, "/api/projects", name="Trailhead"))["id"]
    b = (await post(client, "/api/projects", name="Starling"))["id"]
    one = await post(
        client,
        f"/api/projects/{a}/memory",
        type="warning",
        title="Threaded scene loading crashes Godot",
    )
    await post(
        client,
        f"/api/projects/{b}/memory",
        type="warning",
        title="Godot crashes on threaded scene loading",
    )
    from app.services.health import HealthService

    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        [found] = HealthService(session).share_suggestions()
        assert found["kind"] == "share"
        result = HealthService(session).accept(found["project_id"], found["key"])
    rules = (await client.get("/api/projects/global/memory")).json()
    items = rules["items"] if isinstance(rules, dict) else rules
    assert any(m["human_id"] == result["name"] for m in items)
    links = (await client.get(f"/api/projects/{a}/links", params={"node": one["human_id"]})).json()[
        "links"
    ]
    assert any("(global)" in x["node"]["label"] for x in links)

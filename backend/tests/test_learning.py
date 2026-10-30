"""Link System Phase 2: learning from retrieval, contextual weights, discovery, orphans."""

import pytest
from httpx import AsyncClient

from app.db.session import make_engine, make_session_factory
from app.services.context import ContextService
from app.services.retrieval import RetrievalService, detect_operation

pytestmark = pytest.mark.anyio


async def post(client: AsyncClient, url: str, **body: object) -> dict:
    response = await client.post(url, json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()


async def links_of(client: AsyncClient, pid: str, node: str) -> list[dict]:
    return (await client.get(f"/api/projects/{pid}/links", params={"node": node})).json()["links"]


async def setup(client: AsyncClient) -> tuple[str, dict]:
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    base = f"/api/projects/{pid}"
    task = await post(client, f"{base}/tasks", title="Fix inventory duplication bug")
    manager = await post(client, f"{base}/memory", type="fact", title="InventoryManager state")
    shop = await post(client, f"{base}/memory", type="decision", title="Shop pricing table")
    await post(
        client,
        f"{base}/links",
        source=task["human_id"],
        relationship="affects",
        target=manager["human_id"],
        strength=0.6,
    )
    await post(
        client,
        f"{base}/links",
        source=manager["human_id"],
        relationship="relates_to",
        target=shop["human_id"],
        strength=0.5,
    )
    return pid, {"task": task, "manager": manager, "shop": shop}


def test_operation_detection() -> None:
    assert detect_operation("Fix the duplicated items after loading") == "debugging"
    assert detect_operation("Design the shop layout") == "design"
    assert detect_operation("Write tests for save") == "testing"
    assert detect_operation("Implement the camp system") == "coding"


async def test_feedback_teaches_links_for_one_kind_of_work(
    client: AsyncClient, database_url: str
) -> None:
    pid, rec = await setup(client)
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        pack = ContextService(session).build(
            pid, task=rec["task"]["human_id"], record_for="claude", explore=False
        )
        assert pack.operation == "debugging"
        assert pack.retrieval_id
        assert {i.title for i in pack.items} >= {rec["manager"]["title"], rec["shop"]["title"]}
        result = RetrievalService(session).feedback(
            pid,
            f"R-{pack.retrieval_id[:8]}",
            useful=[rec["manager"]["human_id"]],
            not_useful=[rec["shop"]["human_id"]],
            actor="claude",
        )
    assert result["links_changed"] >= 2

    [to_manager] = [
        x
        for x in await links_of(client, pid, rec["task"]["human_id"])
        if x["node"]["label"] == rec["manager"]["human_id"]
    ]
    assert to_manager["contextual_weights"]["debugging"] > 0.6
    assert to_manager["success_count"] == 1
    assert any(p["source"] == "learning" for p in to_manager["provenance"])

    [to_shop] = [
        x
        for x in await links_of(client, pid, rec["manager"]["human_id"])
        if x["node"]["label"] == rec["shop"]["human_id"]
    ]
    assert to_shop["contextual_weights"]["debugging"] < 0.5
    assert to_shop["failure_count"] == 1
    # The base strength moves only a third as far, so other kinds of work barely notice.
    assert to_shop["strength"] > to_shop["contextual_weights"]["debugging"]


async def test_repeated_noise_fades_for_debugging_but_not_design(
    client: AsyncClient, database_url: str
) -> None:
    pid, rec = await setup(client)
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        for _ in range(3):
            # Not exploring, so every pack shows the noise and every verdict lands.
            pack = ContextService(session).build(
                pid, task=rec["task"]["human_id"], record_for="claude", explore=False
            )
            RetrievalService(session).feedback(
                pid,
                pack.retrieval_id,
                useful=[],
                not_useful=[rec["shop"]["human_id"]],
                actor="claude",
            )
        debugging = ContextService(session).build(pid, task=rec["task"]["human_id"])
        design = ContextService(session).build(
            pid, task=rec["task"]["human_id"], operation="design"
        )
    assert rec["shop"]["title"] not in {i.title for i in debugging.items}
    assert rec["shop"]["title"] in {i.title for i in design.items}


async def test_useful_record_outside_the_pack_gets_linked(
    client: AsyncClient, database_url: str
) -> None:
    pid, rec = await setup(client)
    lone = await post(
        client, f"/api/projects/{pid}/memory", type="warning", title="Loading twice appends"
    )
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        pack = ContextService(session).build(
            pid, task=rec["task"]["human_id"], record_for="codex", explore=False
        )
        result = RetrievalService(session).feedback(
            pid, pack.retrieval_id, useful=[lone["human_id"]], not_useful=[], actor="codex"
        )
        assert result["links_added"] == [lone["human_id"]]
        again = ContextService(session).build(pid, task=rec["task"]["human_id"])
    assert lone["title"] in {i.title for i in again.items}


async def test_checkpoint_mildly_reinforces_the_latest_pack(
    client: AsyncClient, database_url: str
) -> None:
    pid, rec = await setup(client)
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        ContextService(session).build(
            pid, task=rec["task"]["human_id"], record_for="claude", explore=False
        )
    await post(
        client, f"/api/projects/{pid}/checkpoints", title="Fixed it", task_id=rec["task"]["id"]
    )
    [to_manager] = [
        x
        for x in await links_of(client, pid, rec["task"]["human_id"])
        if x["node"]["label"] == rec["manager"]["human_id"]
    ]
    assert 0.6 < to_manager["contextual_weights"]["debugging"] <= 0.63


async def test_new_memory_links_what_it_mentions_and_proposes_candidates(
    client: AsyncClient,
) -> None:
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    base = f"/api/projects/{pid}"
    decision = await post(
        client,
        f"{base}/memory",
        type="decision",
        title="Inventory ownership moved to InventoryManager",
    )
    await post(client, f"{base}/files", path="src/inventory_manager.gd")
    similar = await post(
        client, f"{base}/memory", type="fact", title="Ownership of InventoryManager"
    )
    note = await post(
        client,
        f"{base}/memory",
        type="warning",
        title="Clear runtime state before loading",
        content=f"Follows {decision['human_id']}; see inventory_manager.gd.",
    )
    found = {
        (x["relationship"], x["node"]["label"], x["status"])
        for x in await links_of(client, pid, note["human_id"])
    }
    assert ("references", decision["human_id"], "active") in found
    assert ("references", "src/inventory_manager.gd", "active") in found

    candidates = (await client.get(f"{base}/links/candidates")).json()
    pair = next(
        c
        for c in candidates
        if {c["source"]["label"], c["target"]["label"]}
        == {similar["human_id"], decision["human_id"]}
    )
    assert pair["relationship"] == "relates_to" and pair["confidence"] <= 0.55
    assert "overlap" in pair["why"]

    # A candidate is never travelled until someone confirms it.
    task = await post(client, f"{base}/tasks", title="Anything at all", prefix="ANY")
    await post(
        client,
        f"{base}/links",
        source=task["human_id"],
        relationship="affects",
        target=similar["human_id"],
        strength=0.9,
    )
    pack = (await client.get(f"{base}/context", params={"task": task["human_id"]})).json()
    assert decision["title"] not in {i["title"] for i in pack["items"]}

    rejected = await post(client, f"{base}/links/{pair['link_id']}/reject")
    assert rejected["status"] == "rejected"
    # Rediscovery remembers the no.
    await post(client, f"{base}/links/discover", node=similar["human_id"])
    assert not any(
        c["link_id"] == pair["link_id"]
        for c in (await client.get(f"{base}/links/candidates")).json()
    )

    confirmed = await post(client, f"{base}/links/{pair['link_id']}/confirm")
    assert confirmed["status"] == "active" and confirmed["confidence"] == 1.0
    pack = (await client.get(f"{base}/context", params={"task": task["human_id"]})).json()
    assert decision["title"] in {i["title"] for i in pack["items"]}


async def test_orphans_are_records_nothing_reaches(client: AsyncClient) -> None:
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    base = f"/api/projects/{pid}"
    lone = await post(client, f"{base}/memory", type="note", title="Zebra pattern xylophone")
    a = await post(client, f"{base}/memory", type="fact", title="Alpha")
    b = await post(client, f"{base}/memory", type="fact", title="Beta", related=[a["id"]])
    shelf = await post(client, f"{base}/memory", type="fact", title="Gamma", tags=["Audio"])
    await post(client, f"{base}/shelves", name="Audio")
    orphans = {o["id"] for o in (await client.get(f"{base}/links/orphans")).json()}
    assert lone["human_id"] in orphans
    assert not orphans & {a["human_id"], b["human_id"], shelf["human_id"]}


async def test_pack_explains_what_it_left_out(client: AsyncClient) -> None:
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    base = f"/api/projects/{pid}"
    await post(client, f"{base}/shelves", name="Shop", keywords=["purchase"])
    await post(client, f"{base}/shelves", name="Inventory", keywords=["items"])
    task = await post(client, f"{base}/tasks", title="Duplicated items after loading")
    await post(
        client,
        f"{base}/memory",
        type="decision",
        title="Shop duplicated items pricing",
        tags=["Shop"],
    )
    pack = (await client.get(f"{base}/context", params={"task": task["human_id"]})).json()
    assert pack["operation"] == "debugging"
    assert pack["retrieval_id"] is None  # previews in the app are not recorded
    [left] = pack["excluded"]
    assert left["title"] == "Shop duplicated items pricing"
    assert "dormant" in left["reason"]


async def test_graph_view_and_activation(client: AsyncClient) -> None:
    pid, rec = await setup(client)
    base = f"/api/projects/{pid}"
    view = (await client.get(f"{base}/graph")).json()
    keys = {n["key"] for n in view["nodes"]}
    assert f"task:{rec['task']['id']}" in keys and f"memory:{rec['shop']['id']}" in keys
    assert len(view["links"]) == 2
    lit = (
        await client.get(f"{base}/graph/activation", params={"task": rec["task"]["human_id"]})
    ).json()
    assert lit["operation"] == "debugging"
    assert lit["nodes"][f"memory:{rec['manager']['id']}"] == pytest.approx(0.6)
    assert [
        f"task:{rec['task']['id']}",
        f"memory:{rec['manager']['id']}",
        f"memory:{rec['shop']['id']}",
    ] in lit["paths"]


async def test_one_brain_for_the_whole_workspace(client: AsyncClient) -> None:
    pid, rec = await setup(client)
    other = (await post(client, "/api/projects", name="Starcount"))["id"]
    await post(client, f"/api/projects/{other}/memory", type="fact", title="Separate fact")
    await post(client, f"/api/projects/{other}/shelves", name="Audio")
    await post(client, "/api/projects/global/memory", type="rule", title="Keep commits small")
    brain = (await client.get("/api/brain")).json()
    names = [p["name"] for p in brain["projects"]]
    assert names[0] == "Global rules" and {"Trailhead", "Starcount"} <= set(names)
    by_key = {n["key"]: n for n in brain["nodes"]}
    assert by_key[f"memory:{rec['shop']['id']}"]["project_id"] == pid
    assert len(brain["links"]) == 2
    assert {s["project_id"] for s in brain["shelves"]} == {other}

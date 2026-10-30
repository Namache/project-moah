import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def post(client: AsyncClient, url: str, **body: object) -> dict:
    response = await client.post(url, json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()


async def project(client: AsyncClient, name: str = "Trailhead") -> str:
    return (await post(client, "/api/projects", name=name))["id"]


async def links(client: AsyncClient, pid: str, node: str) -> list[dict]:
    response = await client.get(f"/api/projects/{pid}/links", params={"node": node})
    assert response.status_code == 200, response.text
    return response.json()["links"]


async def pack(client: AsyncClient, pid: str, **params: object) -> dict:
    response = await client.get(f"/api/projects/{pid}/context", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def titles(p: dict) -> set[str]:
    return {i["title"] for i in p["items"]}


async def test_typed_link_reads_both_ways_and_stores_once(client: AsyncClient) -> None:
    pid = await project(client)
    base = f"/api/projects/{pid}"
    grid = await post(client, f"{base}/memory", type="fact", title="InventoryGrid draws slots")
    manager = await post(client, f"{base}/memory", type="fact", title="InventoryManager owns")

    made = await post(
        client,
        f"{base}/links",
        source=grid["human_id"],
        relationship="uses",
        target=f"memory:{manager['human_id']}",
        strength=0.95,
    )
    assert made["relationship"] == "uses"
    assert made["confidence"] == 1.0  # a person made it
    assert made["node"]["label"] == manager["human_id"]

    [back] = await links(client, pid, manager["human_id"])
    assert back["relationship"] == "used_by"
    assert back["direction"] == "incoming"
    assert back["node"]["label"] == grid["human_id"]

    # Giving the inverse name updates the same stored link rather than adding a second one.
    again = await post(
        client,
        f"{base}/links",
        source=manager["human_id"],
        relationship="used_by",
        target=grid["human_id"],
        strength=0.6,
    )
    assert again["id"] == made["id"]
    [forward] = await links(client, pid, grid["human_id"])
    assert forward["strength"] == 0.6

    assert (await client.delete(f"{base}/links/{made['id']}")).status_code == 204
    assert await links(client, pid, grid["human_id"]) == []


async def test_existing_relationships_appear_as_typed_links(client: AsyncClient) -> None:
    pid = await project(client)
    base = f"/api/projects/{pid}"
    parent = await post(client, f"{base}/tasks", title="Inventory system")
    child = await post(client, f"{base}/tasks", title="Fix duplication")
    await post(
        client, f"{base}/tasks/{child['id']}/relationships", type="parent", target=parent["id"]
    )
    rule = await post(
        client, f"{base}/memory", type="rule", title="Clear before load", task_ids=[child["id"]]
    )
    await post(client, f"{base}/files", path="inventory_manager.gd", task_ids=[child["id"]])

    found = {
        (x["relationship"], x["node"]["label"]): x
        for x in await links(client, pid, child["human_id"])
    }
    assert ("part_of", parent["human_id"]) in found
    assert ("governed_by", rule["human_id"]) in found
    assert ("affects", "inventory_manager.gd") in found
    assert all(x["id"] is None for x in found.values())  # built in, nothing was copied

    # Changing a built-in link stores an override instead of a duplicate.
    changed = await post(
        client,
        f"{base}/links",
        source=rule["human_id"],
        relationship="applies_to",
        target=child["human_id"],
        strength=0.95,
    )
    assert changed["origin"] == "memory_task"
    again = [
        x
        for x in await links(client, pid, child["human_id"])
        if x["node"]["label"] == rule["human_id"]
    ]
    assert len(again) == 1 and again[0]["strength"] == 0.95


async def test_links_refuse_bad_input_and_other_projects(client: AsyncClient) -> None:
    pid, other = await project(client), await project(client, "Starling")
    a = await post(client, f"/api/projects/{pid}/memory", type="fact", title="A")
    b = await post(client, f"/api/projects/{other}/memory", type="fact", title="B")
    base = f"/api/projects/{pid}/links"
    cross = await client.post(
        base, json={"source": a["human_id"], "relationship": "uses", "target": f"memory:{b['id']}"}
    )
    assert cross.status_code == 404
    unknown = await client.post(
        base, json={"source": a["human_id"], "relationship": "likes", "target": a["human_id"]}
    )
    assert unknown.status_code == 422
    self_link = await client.post(
        base, json={"source": a["human_id"], "relationship": "uses", "target": a["human_id"]}
    )
    assert self_link.status_code == 409


async def test_deleting_a_record_removes_its_links(client: AsyncClient) -> None:
    pid = await project(client)
    base = f"/api/projects/{pid}"
    a = await post(client, f"{base}/memory", type="fact", title="A")
    b = await post(client, f"{base}/memory", type="fact", title="B")
    await post(
        client, f"{base}/links", source=a["human_id"], relationship="explains", target=b["human_id"]
    )
    shelf = await post(client, f"{base}/shelves", name="Inventory")
    await post(client, f"{base}/shelves/{shelf['id']}/members", node=b["human_id"])
    assert (await client.delete(f"{base}/memory/{b['id']}")).status_code == 204
    assert await links(client, pid, a["human_id"]) == []
    detail = (await client.get(f"{base}/shelves/Inventory")).json()
    assert detail["members"] == []


async def test_shelves_hold_records_directly_and_through_tags(client: AsyncClient) -> None:
    pid = await project(client)
    base = f"/api/projects/{pid}"
    tagged = await post(
        client, f"{base}/memory", type="rule", title="Tagged rule", tags=["Save System"]
    )
    placed = await post(client, f"{base}/memory", type="fact", title="Placed fact")
    parent = await post(client, f"{base}/shelves", name="Architecture")
    shelf = await post(
        client,
        f"{base}/shelves",
        name="Save System",
        keywords=["Persistence", "load"],
        parent="Architecture",
    )
    assert shelf["parent_id"] == parent["id"]
    assert shelf["keywords"] == ["persistence", "load"]
    await post(client, f"{base}/shelves/save system/members", node=placed["human_id"])
    detail = (await client.get(f"{base}/shelves/{shelf['id']}")).json()
    assert {m["label"] for m in detail["members"]} == {tagged["human_id"], placed["human_id"]}

    cycle = await client.patch(f"{base}/shelves/Architecture", json={"parent": "Save System"})
    assert cycle.status_code == 422
    duplicate = await client.post(f"{base}/shelves", json={"name": "save  system"})
    assert duplicate.status_code == 409

    activation = (
        await client.get(f"{base}/shelves/activation", params={"text": "items vanish on loading"})
    ).json()
    by_name = {a["name"]: a for a in activation}
    assert by_name["Save System"]["active"] is True
    # The parent wakes through its sub-shelf, but less strongly.
    assert 0.3 <= by_name["Architecture"]["activation"] < by_name["Save System"]["activation"]


async def build_game(client: AsyncClient) -> tuple[str, dict]:
    """Inventory and Shop shelves, a debugging task, and memory spread across them."""
    pid = await project(client)
    base = f"/api/projects/{pid}"
    await post(client, f"{base}/shelves", name="Inventory", keywords=["items", "loot"])
    await post(client, f"{base}/shelves", name="Shop", keywords=["purchase", "currency"])
    task = await post(
        client, f"{base}/tasks", title="Fix duplicated items after loading", prefix="INV"
    )

    def memory(**body: object):
        return post(client, f"{base}/memory", **body)

    rec = {
        "task": task,
        "manager": await memory(
            type="fact", title="InventoryManager holds runtime state", tags=["Inventory"]
        ),
        "rule": await memory(
            type="rule", title="UI never mutates state directly", tags=["Inventory"]
        ),
        "save": await memory(type="decision", title="SaveManager replaces state on restore"),
        "lesson": await memory(type="warning", title="Clear state before restoring"),
        "far": await memory(type="note", title="Four hops away"),
        "shop": await memory(
            type="decision", title="Shop prices duplicated items too", tags=["Shop"]
        ),
    }
    link = f"{base}/links"
    await post(
        client,
        link,
        source=task["human_id"],
        relationship="affects",
        target=rec["manager"]["human_id"],
        strength=0.9,
    )
    await post(
        client,
        link,
        source=rec["manager"]["human_id"],
        relationship="depends_on",
        target=rec["save"]["human_id"],
        strength=0.8,
    )
    await post(
        client,
        link,
        source=rec["save"]["human_id"],
        relationship="explains",
        target=rec["lesson"]["human_id"],
        strength=0.9,
    )
    await post(
        client,
        link,
        source=rec["lesson"]["human_id"],
        relationship="relates_to",
        target=rec["far"]["human_id"],
        strength=1.0,
    )
    return pid, rec


async def test_context_pack_walks_links_and_wakes_shelves(client: AsyncClient) -> None:
    pid, rec = await build_game(client)
    p = await pack(client, pid, task=rec["task"]["human_id"])
    found = titles(p)
    assert rec["manager"]["title"] in found  # one hop
    assert rec["save"]["title"] in found  # two hops
    assert rec["lesson"]["title"] in found  # three hops: strong links carry it
    # Four hops is within depth, but notes rank last and each hop decays the path.
    lesson = next(i for i in p["items"] if i["title"] == rec["lesson"]["title"])
    save = next(i for i in p["items"] if i["title"] == rec["save"]["title"])
    assert lesson["confidence"] < save["confidence"]
    assert rec["rule"]["title"] in found  # woke with the Inventory shelf
    # "items" appears in the task, but nothing ties the task to Shop beyond a word.
    assert rec["shop"]["title"] not in found
    shelves = {s["name"]: s for s in p["shelves"]}
    assert shelves["Inventory"]["active"] and not shelves["Shop"]["active"]
    assert "ACTIVE SHELVES\nInventory" in p["text"]
    assert "Dormant, left out: Shop" in p["text"]
    reason = next(i["reason"] for i in p["items"] if i["title"] == rec["save"]["title"])
    assert reason == (
        f"via {rec['task']['human_id']} → affects → {rec['manager']['human_id']} → depends on → "
        f"{rec['save']['human_id']}"
    )
    rule_reason = next(i["reason"] for i in p["items"] if i["title"] == rec["rule"]["title"])
    assert rule_reason == "on the Inventory shelf"


async def test_dormant_shelf_keeps_search_matches_out(client: AsyncClient) -> None:
    pid, rec = await build_game(client)
    # Without the Shop shelf, the word overlap alone brings the shop decision in.
    p = await pack(client, pid, task=rec["task"]["human_id"])
    assert p["omitted"].get("dormant shelf", 0) >= 1
    # A person naming it still wins over dormancy.
    named = await pack(client, pid, task=rec["task"]["human_id"], include=rec["shop"]["human_id"])
    assert rec["shop"]["title"] in titles(named)


async def test_negative_links_keep_dots_apart(client: AsyncClient) -> None:
    pid, rec = await build_game(client)
    base = f"/api/projects/{pid}"
    await post(
        client,
        f"{base}/links",
        source=rec["task"]["human_id"],
        relationship="independent_of",
        target=rec["save"]["human_id"],
    )
    p = await pack(client, pid, task=rec["task"]["human_id"])
    assert rec["manager"]["title"] in titles(p)
    assert rec["save"]["title"] not in titles(p)


async def test_weak_links_fade_out(client: AsyncClient) -> None:
    pid, rec = await build_game(client)
    base = f"/api/projects/{pid}"
    await post(
        client,
        f"{base}/links",
        source=rec["manager"]["human_id"],
        relationship="depends_on",
        target=rec["save"]["human_id"],
        strength=0.1,
    )
    p = await pack(client, pid, task=rec["task"]["human_id"])
    assert rec["save"]["title"] not in titles(p)


async def test_files_reached_through_links_join_the_pack(client: AsyncClient) -> None:
    pid, rec = await build_game(client)
    base = f"/api/projects/{pid}"
    await post(client, f"{base}/files", path="save_manager.gd", memory_ids=[rec["manager"]["id"]])
    p = await pack(client, pid, task=rec["task"]["human_id"])
    item = next(i for i in p["items"] if i["title"] == "save_manager.gd")
    assert item["reason"].startswith(f"via {rec['task']['human_id']} → affects")


async def test_project_without_shelves_reports_none(client: AsyncClient) -> None:
    pid = await project(client)
    task = await post(client, f"/api/projects/{pid}/tasks", title="Anything")
    p = await pack(client, pid, task=task["human_id"])
    assert p["shelves"] == []
    assert "ACTIVE SHELVES" not in p["text"]


async def test_two_routes_outrank_one_and_sampling_explores(
    client: AsyncClient, database_url: str
) -> None:
    import random

    from app.db.session import make_engine, make_session_factory
    from app.services.graph import GraphService, Node

    pid = await project(client)
    base = f"/api/projects/{pid}"
    task = await post(client, f"{base}/tasks", title="Tune the climbing curve", prefix="CLIM")
    made = {
        name: await post(client, f"{base}/memory", type="fact", title=f"Record {name}")
        for name in ("a", "b", "c", "twice", "once")
    }
    for source, target in (
        (task, "a"),
        (task, "b"),
        (task, "c"),
        ("a", "twice"),
        ("b", "twice"),
        ("c", "once"),
    ):
        await post(
            client,
            f"{base}/links",
            source=source["human_id"] if isinstance(source, dict) else made[source]["human_id"],
            relationship="relates_to",
            target=made[target]["human_id"],
            strength=0.6,
        )
    p = await pack(client, pid, task=task["human_id"], detail="detailed")
    confidence = {i["title"]: i["confidence"] for i in p["items"] if i.get("confidence")}
    # Reached by two routes of the same strength: the evidence adds up, under 1.
    assert confidence["Record once"] < confidence["Record twice"] < 1

    engine = make_engine(database_url)
    with make_session_factory(engine)() as session:
        graph = GraphService(session)
        start = {Node("task", task["id"]): 1.0}
        plain = graph.traverse(pid, start, max_depth=3)
        assert plain == graph.traverse(pid, start, max_depth=3)  # the mean is deterministic
        sampled = [
            graph.traverse(pid, start, max_depth=3, sample=random.Random(seed)) for seed in range(8)
        ]
        once = Node("memory", made["once"]["id"])
        # Untried links are uncertain, so samples spread around the learned strength.
        assert len({round(s[once].score, 3) for s in sampled if once in s}) > 1
    engine.dispose()


async def test_global_shelves_wake_in_project_packs_and_paths_show(client: AsyncClient) -> None:
    pid = await project(client)
    base = f"/api/projects/{pid}"
    await post(client, "/api/projects/global/shelves", name="UI", keywords=["mobile"])
    await post(
        client,
        "/api/projects/global/memory",
        type="fact",
        title="Padding and a clear centrepiece work best on phones",
        tags=["UI"],
    )
    await post(client, f"{base}/shelves", name="Gameplay")
    await post(client, f"{base}/shelves", name="Combat", parent="Gameplay")
    task = await post(
        client, f"{base}/tasks", title="Make combat UI easier on mobile", prefix="CLIM"
    )
    p = await pack(client, pid, task=task["human_id"])
    assert "Padding and a clear centrepiece work best on phones" in p["text"]
    assert "Gameplay > Combat" in p["text"] and "Global: UI" in p["text"]
    routed = next(i for i in p["items"] if i["title"].startswith("Padding"))
    assert routed["reason"] == "on the Global UI shelf"
    # A Global shelf the work doesn't mention stays out of the pack.
    other = await post(client, f"{base}/tasks", title="Balance the boss fight", prefix="CLIM")
    assert "Padding" not in (await pack(client, pid, task=other["human_id"]))["text"]

from collections import Counter

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def post(client: AsyncClient, path: str, **body: object) -> dict:
    response = await client.post(path, json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()


async def pack(client: AsyncClient, pid: str, **params: object) -> dict:
    response = await client.get(f"/api/projects/{pid}/context", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def build_project(client: AsyncClient, name: str, party: int) -> dict:
    """A project with a rich task and overlapping vocabulary ("party", "camp", "capacity")."""
    pid = (await client.post("/api/projects", json={"name": name})).json()["id"]
    base = f"/api/projects/{pid}"
    ms = await post(client, f"{base}/milestones", name="Demo", status="active")
    dep = await post(client, f"{base}/tasks", title="Save schema migration", prefix="SAVE")
    task = await post(
        client,
        f"{base}/tasks",
        title="Camp party capacity",
        prefix="CAMP",
        milestone_id=ms["id"],
        description="Prevent recruitment when the party is full. Extra detail follows."
        "\n\nSecond paragraph.",
        next_action="Add the migration fallback for old saves.",
        acceptance_criteria=["Track capacity", "Block recruitment", "Migrate old saves"],
    )
    await client.patch(
        f"{base}/tasks/{task['id']}/criteria/{task['acceptance_criteria'][0]['id']}",
        json={"is_completed": True},
    )
    await post(
        client,
        f"{base}/tasks/{task['id']}/relationships",
        type="depends_on",
        target=dep["human_id"],
    )
    await post(client, f"{base}/tasks/{task['id']}/start")

    def memory(**body: object):
        return post(client, f"{base}/memory", **body)

    old = await memory(
        type="decision",
        title=f"Earlier party cap {party + 10}",
        content="Old value",
        task_ids=[task["id"]],
    )
    await client.post(
        f"{base}/memory/{old['id']}/supersede",
        json={"title": f"Party size is {party}", "content": "Current value"},
    )
    await memory(
        type="decision",
        title="Camp capacity limits recruited folk",
        is_locked=True,
        importance="high",
        task_ids=[task["id"]],
    )
    await memory(type="decision", title="Unrelated audio decision", content="mixer buses")
    await memory(type="rule", title="Save migrations preserve older saves", task_ids=[task["id"]])
    await memory(type="rule", title="Rule about camp party capacity naming")
    await memory(
        type="bug",
        title="Old saves contain no camp_capacity",
        task_ids=[task["id"]],
        importance="high",
    )
    await memory(type="idea", title="Tents raise party capacity", task_ids=[task["id"]])
    await memory(type="idea", title="Totally unrelated pet idea")
    await memory(
        type="fact",
        title="Hidden party fact",
        content="secret",
        ai_visibility="hidden",
        task_ids=[task["id"]],
    )
    await memory(
        type="note", title="Manual party note", ai_visibility="manual_only", task_ids=[task["id"]]
    )
    archived = await memory(type="rule", title="Archived party rule", task_ids=[task["id"]])
    await client.post(f"{base}/memory/{archived['id']}/archive")
    await memory(type="rule", title="Always use signals", ai_visibility="always", importance="high")
    await post(
        client,
        f"{base}/checkpoints",
        title="Capacity works",
        summary="Capacity system is functional.",
        remaining_work="Save migration",
        task_id=task["id"],
    )
    return {"id": pid, "task": task["human_id"], "dep": dep["human_id"]}


async def test_pack_follows_the_safety_rules(client: AsyncClient) -> None:
    a = await build_project(client, "Trailhead", 5)
    b = await build_project(client, "Starling", 4)
    result = await pack(client, a["id"], task=a["task"], detail="detailed")
    text = result["text"]

    assert "CAMP-001" in text and "Capacity system is functional." in text
    current = {i["title"] for i in result["items"] if i["section"] == "decisions"}
    assert "Party size is 5" in current and "Earlier party cap 15" not in current  # successor only
    assert "Starling" not in text and "Party size is 4" not in text  # the other project never leaks
    assert "Unrelated audio decision" not in text and "Totally unrelated pet idea" not in text
    assert "Hidden party fact" not in text and "secret" not in text
    assert "Manual party note" not in text and "Archived party rule" not in text
    assert "Always use signals" in text  # always-visible memory
    assert "Tents raise party capacity" in text
    assert "IDEAS UNDER CONSIDERATION (NOT REQUIREMENTS)" in text
    assert result["omitted"]["hidden"] == 1 and result["omitted"]["manual only"] == 1
    assert (
        "Waiting on SAVE-001" in text
        and "✗ Migrate old saves" in text
        and "✓ Track capacity" in text
    )
    assert "Second paragraph" not in text  # goal is the first paragraph only
    # Same checks the other way round.
    other = await pack(client, b["id"], task=b["task"], detail="detailed")
    assert "Party size is 4" in other["text"] and "Party size is 5" not in other["text"]
    assert "Trailhead" not in other["text"]

    manual = await pack(client, a["id"], task=a["task"], include="NOTE-001")
    assert "Manual party note" in manual["text"]
    hidden_try = await pack(client, a["id"], task=a["task"], include="FACT-001")
    assert "secret" not in hidden_try["text"]
    excluded = await pack(client, a["id"], task=a["task"], exclude="RULE-004")
    assert "Always use signals" not in excluded["text"]


async def test_detail_levels_and_budgets(client: AsyncClient) -> None:
    a = await build_project(client, "Trailhead", 5)
    sizes = {
        d: (await pack(client, a["id"], task=a["task"], detail=d))["estimated_tokens"]
        for d in ("minimal", "balanced", "detailed")
    }
    assert sizes["minimal"] < sizes["balanced"] < sizes["detailed"]
    minimal = await pack(client, a["id"], task=a["task"], detail="minimal")
    assert "✓ Track capacity" not in minimal["text"] and "✗ Migrate old saves" in minimal["text"]
    assert "Camp capacity limits recruited folk" in minimal["text"]  # locked decision survives
    assert "PROJECT RULES" not in minimal["text"]
    # A bug linked to the task survives minimal: the known trap is what a short pack must keep.
    assert "Old saves contain no camp_capacity" in minimal["text"]
    assert "Capacity system is functional." in minimal["text"]
    base = f"/api/projects/{a['id']}"
    await post(
        client, f"{base}/memory", type="warning", title="Pinned audio warning", is_pinned=True
    )
    await post(client, f"{base}/memory", type="warning", title="Recruitment ignores party capacity")
    minimal = await pack(client, a["id"], task=a["task"], detail="minimal")
    assert "Recruitment ignores party capacity" in minimal["text"]  # matches the task's words
    assert "Pinned audio warning" not in minimal["text"]  # pinned alone is not a match

    # A tiny budget keeps the essentials, whole, and says it is over budget.
    tiny = await pack(client, a["id"], task=a["task"], detail="detailed", budget=100)
    assert tiny["over_budget"] == (tiny["estimated_tokens"] > 100)
    assert tiny["estimated_tokens"] < 400  # essentials only, far below the detailed size
    for essential in (
        "CAMP-001",
        "✗ Migrate old saves",
        "Add the migration fallback for old saves.",
    ):
        assert essential in tiny["text"]
    assert "Always use signals" not in tiny["text"] and tiny["omitted"]["budget"] > 0
    # Mid budgets drop the least important tiers first and never split an item.
    mid = await pack(client, a["id"], task=a["task"], detail="detailed", budget=200)
    assert mid["estimated_tokens"] <= max(200, tiny["estimated_tokens"])
    for item in mid["items"]:
        assert item["tokens"] > 0
    assert mid["estimated_tokens"] < sizes["detailed"]
    assert abs(sum(s["tokens"] for s in mid["sections"]) - mid["estimated_tokens"]) <= 14
    kept = {i["title"] for i in mid["items"]}
    if "Camp capacity limits recruited folk" not in kept:
        assert (
            not {"Always use signals", "Tents raise party capacity"} & kept
        )  # later tiers go first
    again = await pack(client, a["id"], task=a["task"], detail="detailed", budget=200)
    assert again["text"] == mid["text"]  # deterministic


async def test_no_task_uses_focus_then_overview_and_validates(client: AsyncClient) -> None:
    a = await build_project(client, "Trailhead", 5)
    focused = await pack(client, a["id"])
    assert focused["task"] == "CAMP-001" and "current focus" in focused["warnings"][0]
    await client.put(f"/api/projects/{a['id']}/focus", json={"task": None})
    overview = await pack(client, a["id"])
    assert overview["task"] is None and "project overview" in overview["warnings"][0]
    assert "CAMP-001 Camp party capacity (in progress" in overview["text"]
    assert "Always use signals" in overview["text"]
    assert "Unrelated audio decision" not in overview["text"]
    searched = await pack(client, a["id"], q="audio mixer")
    assert "Unrelated audio decision" in searched["text"]
    assert (
        await client.get(f"/api/projects/{a['id']}/context", params={"detail": "huge"})
    ).status_code == 422
    assert (
        await client.get(f"/api/projects/{a['id']}/context", params={"budget": 5})
    ).status_code == 422
    assert (
        await client.get(f"/api/projects/{a['id']}/context", params={"task": "NOPE-1"})
    ).status_code == 404
    other = await build_project(client, "Starling", 4)
    cross = await client.get(f"/api/projects/{a['id']}/context", params={"task": other["task"]})
    assert (
        cross.status_code == 200 and "Starling" not in cross.text
    )  # CAMP-001 resolves inside A only


async def test_handoff_is_plain_text_with_completed_remaining_and_next(client: AsyncClient) -> None:
    a = await build_project(client, "Trailhead", 5)
    b = await build_project(client, "Starling", 4)
    response = await client.get(f"/api/projects/{a['id']}/handoff", params={"task": a["task"]})
    assert response.status_code == 200
    text = response.json()["text"]
    assert text.startswith("Handoff from Project Moah.")
    for heading in (
        "PROJECT\nTrailhead",
        "TASK\nCAMP-001",
        "COMPLETED\n✓ Track capacity",
        "REMAINING\n✗ Block recruitment",
        "NEXT ACTION\nAdd the migration fallback",
        "IMPORTANT DECISIONS",
        "KNOWN ISSUES",
        "LATEST CHECKPOINT\nCapacity works",
    ):
        assert heading in text, heading
    assert "- Save migration" in text  # remaining work from the checkpoint
    assert "BLOCKED BY\nWaiting on SAVE-001" in text
    assert (
        "Starling" not in text and "Party size is 4" not in text and "Hidden party fact" not in text
    )
    assert "Tents raise party capacity" not in text  # ideas are not handoff material
    other = (
        await client.get(f"/api/projects/{b['id']}/handoff", params={"task": b["task"]})
    ).json()["text"]
    assert "Party size is 4" in other and "Trailhead" not in other
    await client.put(f"/api/projects/{a['id']}/focus", json={"task": None})
    overview = (await client.get(f"/api/projects/{a['id']}/handoff")).json()
    assert overview["task"] is None and "No task is in focus" in overview["text"]
    assert (
        await client.get(f"/api/projects/{a['id']}/handoff", params={"budget": 10})
    ).status_code == 422


async def test_related_memory_is_found_when_only_some_words_match(client) -> None:
    project = (await client.post("/api/projects", json={"name": "Relevance"})).json()["id"]
    task = (
        await client.post(
            f"/api/projects/{project}/tasks",
            json={"title": "Fix login redirect on Safari", "prefix": "WEB"},
        )
    ).json()
    await client.post(
        f"/api/projects/{project}/memory",
        json={"type": "warning", "title": "Safari drops cookies on redirect"},
    )
    pack = (
        await client.get(f"/api/projects/{project}/context", params={"task": task["human_id"]})
    ).json()
    assert "Safari drops cookies on redirect" in str(pack)


def test_budget_takes_the_best_set_and_skips_repeats() -> None:
    from app.services.context import ContextService, Item

    def record(title: str, text: str, score: float, tier: int = 3) -> Item:
        return Item("decisions", "memory:decision", title, title, text, tier, score)

    long = record("Long one", "x " * 600, 60)  # ~300 tokens, scores most on its own
    short_a = record("Short A", "Recruitment checks party capacity first.", 50)
    short_b = record("Short B", "Tents add two camp slots each.", 50)
    omitted: Counter[str] = Counter()
    kept, _ = ContextService._fit([long, short_a, short_b], 100, "balanced", omitted)
    # In line, the long record came first and would have blocked both short ones.
    assert short_a in kept and short_b in kept and long not in kept
    assert omitted["budget"] == 1

    first = record("Camp capacity", "Camp capacity limits recruited folk to six", 50)
    again = record("Camp capacity again", "Camp capacity limits recruited folk to six", 40)
    omitted = Counter()
    kept, _ = ContextService._fit([first, again], 1500, "balanced", omitted)
    assert kept == [first] and omitted["repeats"] == 1


async def test_no_record_is_out_of_reach_in_a_large_project(client: AsyncClient) -> None:
    pid = (await client.post("/api/projects", json={"name": "Big"})).json()["id"]
    base = f"/api/projects/{pid}"
    # The oldest, least important record: packs used to read only the first 500 records.
    await post(
        client,
        f"{base}/memory",
        type="fact",
        title="Zeppelin docks use copper bolts",
        importance="low",
    )
    for n in range(505):
        await post(client, f"{base}/memory", type="note", title=f"Filler note {n}")
    found = await pack(client, pid, q="zeppelin docks")
    assert "Zeppelin docks use copper bolts" in found["text"]

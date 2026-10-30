"""Brain health says what agents can actually find and how much they use the brain (2026-10-18)."""

import pytest
from httpx import AsyncClient

from app.db.session import make_engine, make_session_factory
from app.services.retrieval import RetrievalService

pytestmark = pytest.mark.anyio


async def post(client: AsyncClient, url: str, **body: object) -> dict:
    response = await client.post(url, json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()


async def memory(client: AsyncClient, pid: str, title: str, **fields: object) -> dict:
    return await post(
        client, f"/api/projects/{pid}/memory", title=title, **{"type": "fact", **fields}
    )


async def link(client: AsyncClient, pid: str, a: str, rel: str, b: str) -> None:
    await post(client, f"/api/projects/{pid}/links", source=a, relationship=rel, target=b)


def project_health(brain: dict, name: str) -> dict:
    return next(p for p in brain["projects"] if p["name"] == name)


async def test_orphans_are_memory_only_a_word_search_finds(client: AsyncClient) -> None:
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    base = f"/api/projects/{pid}"
    lone = await memory(client, pid, "Camp music loops every four minutes")
    await memory(client, pid, "Never ship debug saves", ai_visibility="always")
    await memory(client, pid, "Old trailer notes", ai_visibility="manual_only")
    a = await memory(client, pid, "Wyrm breath ignores armour")
    b = await memory(client, pid, "Wyrm fight lasts three phases")
    await link(client, pid, a["human_id"], "relates_to", b["human_id"])
    task = await post(client, f"{base}/tasks", title="Tune the wyrm fight")
    await link(client, pid, task["human_id"], "relates_to", a["human_id"])

    orphans = [o["id"] for o in (await client.get(f"{base}/links/orphans")).json()]
    # Always-visible memory is in every pack and manual-only memory only when named, so a
    # link would not change how either is found.
    assert orphans == [lone["human_id"]]
    health = project_health((await client.get("/api/brain/health")).json(), "Trailhead")
    # The task has no memory of its own to find, and is not counted.
    assert health["memory"] == 3 and health["orphans"] == 1


async def test_global_records_only_routes_deliver_are_orphans(client: AsyncClient) -> None:
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    await post(client, "/api/projects/global/memory", type="rule", title="Ask before big systems")
    note = await post(client, "/api/projects/global/memory", type="note", title="Reply in English")
    tool = await post(
        client, "/api/projects/global/memory", type="fact", title="Godot comes from Steam"
    )
    engine = await memory(client, pid, "Engine setup for the build machine")
    await link(client, pid, engine["human_id"], "relates_to", f"global:{tool['human_id']}")

    orphans = [o["id"] for o in (await client.get("/api/projects/global/links/orphans")).json()]
    # Global rules are in every pack; the fact is reached through Trailhead's route; the note
    # reaches no agent at all.
    assert orphans == [note["human_id"]]
    health = project_health((await client.get("/api/brain/health")).json(), "Global rules")
    assert health["memory"] == 2 and health["orphans"] == 1


async def test_health_counts_recent_use_and_what_links_added(
    client: AsyncClient, database_url: str
) -> None:
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    base = f"/api/projects/{pid}"
    task = await post(client, f"{base}/tasks", title="Tune the wyrm fight")
    a = await memory(client, pid, "Wyrm breath ignores armour")
    await post(client, f"{base}/checkpoints", title="Tuned phase one", summary="Done")
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        retrieval = RetrievalService(session)
        hop = [["task", task["id"], "memory", a["id"], "relates_to"]]
        first = retrieval.record(
            pid,
            task_id=task["id"],
            operation="implement",
            query=None,
            agent="claude",
            items=[
                {"kind": "memory", "id": a["id"], "label": a["human_id"], "path": hop},
                {"kind": "memory", "id": "x", "label": "FACT-9", "path": []},
            ],
        )
        retrieval.record(
            pid, task_id=None, operation="explore", query="wyrm", agent="codex", items=[]
        )
        first.outcome = "success"
        session.commit()

    health = project_health((await client.get("/api/brain/health")).json(), "Trailhead")
    r = health["retrieval"]
    assert (r["packs"], r["packs_recent"], r["feedback_recent"]) == (2, 2, 1)
    assert r["through_links"] == 0.5
    assert health["checkpoints_recent"] == 1


async def test_a_shelf_of_memory_is_not_offered_tasks(client: AsyncClient) -> None:
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    base = f"/api/projects/{pid}"
    lessons = [
        await memory(client, pid, title, type="rule")
        for title in ("Props need depth", "Highlights must be real", "One look per element")
    ]
    shelf = await post(client, f"{base}/shelves", name="Lesson")
    for m in lessons:
        await post(client, f"{base}/shelves/{shelf['id']}/members", node=m["human_id"])
    # A screen task follows three lessons; a decision builds on two of them.
    task = await post(client, f"{base}/tasks", title="Choose Region screen")
    decision = await memory(client, pid, "Maps are pen and ink", type="decision")
    for m in lessons:
        await link(client, pid, task["human_id"], "governed_by", m["human_id"])
    for m in lessons[:2]:
        await link(client, pid, decision["human_id"], "refines", m["human_id"])

    brain = (await client.get("/api/brain/health")).json()
    adds = [s for s in brain["suggestions"] if s["kind"] == "add_member"]
    assert [s["records"] for s in adds] == [
        [{"label": decision["human_id"], "title": "Maps are pen and ink"}]
    ]

import sqlite3

import pytest
from httpx import AsyncClient

from app.schemas.memory import MemoryCreate, MemorySupersede, MemoryUpdate
from app.services.memory import MemoryService
from tests.conftest import app_client

pytestmark = pytest.mark.anyio


async def project(client: AsyncClient, name: str) -> str:
    return (await client.post("/api/projects", json={"name": name})).json()["id"]


async def memo(client: AsyncClient, pid: str, **body: object) -> dict:
    payload = {"type": "decision", "title": "Party size", **body}
    response = await client.post(f"/api/projects/{pid}/memory", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def test_types_ids_tags_task_links_and_filters(client: AsyncClient) -> None:
    pid = await project(client, "Trailhead")
    task = (await client.post(f"/api/projects/{pid}/tasks", json={"title": "Camp"})).json()
    dec = await memo(
        client,
        pid,
        title="Starting capacity is 6",
        tags=["gameplay", "Gameplay"],
        task_ids=[task["human_id"]],
        importance="high",
        is_pinned=True,
    )
    assert dec["human_id"] == "DEC-001" and dec["status"] == "active"
    assert dec["tags"] == ["gameplay"] and [t["id"] for t in dec["tasks"]] == [task["id"]]
    assert (await memo(client, pid, title="Another"))["human_id"] == "DEC-002"
    idea = await memo(client, pid, type="idea", title="Tents add capacity", content="Maybe")
    rule = await memo(client, pid, type="rule", title="Use signals", ai_visibility="always")
    bug = await memo(client, pid, type="bug", title="Old saves have no capacity")
    assert [m["human_id"] for m in (idea, rule, bug)] == ["IDEA-001", "RULE-001", "BUG-001"]

    base = f"/api/projects/{pid}/memory"
    listed = (await client.get(base)).json()
    assert listed[0]["id"] == dec["id"]  # pinned first
    alphabetic = (await client.get(f"{base}?sort=title_asc")).json()
    assert [m["title"] for m in alphabetic] == sorted(m["title"] for m in listed)
    assert (await client.get(f"{base}?sort=unknown")).status_code == 422
    assert {m["type"] for m in (await client.get(f"{base}?type=idea&type=bug")).json()} == {
        "idea",
        "bug",
    }
    assert [m["id"] for m in (await client.get(f"{base}?tag=GAMEPLAY")).json()] == [dec["id"]]
    assert [m["id"] for m in (await client.get(f"{base}?task={task['human_id']}")).json()] == [
        dec["id"]
    ]
    assert [m["id"] for m in (await client.get(f"{base}?visibility=always")).json()] == [rule["id"]]
    assert [m["id"] for m in (await client.get(f"{base}?q=tents")).json()] == [idea["id"]]
    assert (await client.get(f"{base}?q=%25")).json() == []  # wildcards are literal
    assert (await client.get(f"{base}/dec-001")).json()["id"] == dec["id"]
    counts = (await client.get(f"{base}/counts")).json()
    assert counts["by_type"] == {"decision": 2, "idea": 1, "rule": 1, "bug": 1}
    assert counts["pinned"] == 1


async def test_supersession_keeps_history_and_resolves_the_current_record(
    client: AsyncClient,
) -> None:
    pid = await project(client, "Starling")
    base = f"/api/projects/{pid}/memory"
    old = await memo(client, pid, title="Party size is 5", tags=["party"], is_pinned=True)
    new = (
        await client.post(f"{base}/{old['id']}/supersede", json={"title": "Party size is 4"})
    ).json()
    assert new["human_id"] == "DEC-002" and new["type"] == "decision"
    assert (
        new["supersedes"]["human_id"] == "DEC-001" and new["tags"] == ["party"] and new["is_pinned"]
    )

    assert [m["id"] for m in (await client.get(base)).json()] == [new["id"]]  # normal lists skip it
    old_now = (await client.get(f"{base}/DEC-001")).json()
    assert old_now["status"] == "superseded" and old_now["superseded_by"]["human_id"] == "DEC-002"
    assert [m["id"] for m in (await client.get(f"{base}?status=superseded")).json()] == [old["id"]]

    again = await client.post(f"{base}/{old['id']}/supersede", json={"title": "Party size is 3"})
    assert again.status_code == 409
    third = (
        await client.post(f"{base}/{new['id']}/supersede", json={"title": "Party size is 6"})
    ).json()
    history = (await client.get(f"{base}/DEC-001/history")).json()
    assert [m["human_id"] for m in history["chain"]] == ["DEC-001", "DEC-002", "DEC-003"]
    assert history["current_id"] == third["id"]
    assert (
        await client.patch(f"{base}/DEC-001", json={"title": "rewrite history"})
    ).status_code == 409
    assert (await client.delete(f"{base}/DEC-001")).status_code == 409
    assert (await client.delete(f"{base}/{third['id']}")).status_code == 409
    assert (await client.get(f"{base}/DEC-001/history")).json() == history
    assert [m["id"] for m in (await client.get(base)).json()] == [third["id"]]


async def test_locked_memory_cannot_be_changed_by_agents(
    client: AsyncClient, database_url: str
) -> None:
    pid = await project(client, "Trailhead")
    locked = await memo(client, pid, title="Base camp capacity is 6", is_locked=True)
    base = f"/api/projects/{pid}/memory"
    engine_url = database_url
    from app.db.session import make_engine, make_session_factory

    engine = make_engine(engine_url)
    try:
        with make_session_factory(engine)() as session:
            service = MemoryService(session)
            for attempt in (
                lambda: service.update(pid, locked["id"], MemoryUpdate(content="8"), actor="codex"),
                lambda: service.update(
                    pid, locked["id"], MemoryUpdate(tags=["reclassified"]), actor="codex"
                ),
                lambda: service.update(
                    pid, locked["id"], MemoryUpdate(source_type="repository"), actor="codex"
                ),
                lambda: service.update(
                    pid, locked["id"], MemoryUpdate(source_reference="other"), actor="codex"
                ),
                lambda: service.update(
                    pid, locked["id"], MemoryUpdate(is_locked=False), actor="codex"
                ),
                lambda: service.supersede(
                    pid, locked["id"], MemorySupersede(title="Capacity 8"), actor="claude"
                ),
                lambda: service.invalidate(pid, locked["id"], actor="codex"),
                lambda: service.archive(pid, locked["id"], actor="codex"),
                lambda: service.delete(pid, locked["id"], actor="codex"),
                lambda: service.create(
                    pid, MemoryCreate(type="rule", title="x", is_locked=True), actor="codex"
                ),
            ):
                with pytest.raises(Exception) as caught:
                    attempt()
                assert getattr(caught.value, "status_code", None) == 423
            unchanged = service.read(pid, locked["id"])
            assert (unchanged.title, unchanged.content, unchanged.is_locked, unchanged.tags) == (
                locked["title"],
                "",
                True,
                [],
            )
            assert unchanged.source_type is None and unchanged.source_reference is None
            # Agents may still add their own, unlocked memory, marked with where it came from.
            created = service.create(
                pid, MemoryCreate(type="note", title="Agent note"), actor="codex"
            )
            assert (created.source_type, created.source_reference) == ("agent", "codex")
            # Pinning a locked record is harmless, so it stays allowed.
            assert service.update(
                pid, locked["id"], MemoryUpdate(is_pinned=True), actor="codex"
            ).is_pinned
    finally:
        engine.dispose()

    # A person may edit it, but must unlock before a permanent delete.
    assert (
        await client.patch(f"{base}/{locked['id']}", json={"content": "Confirmed"})
    ).status_code == 200
    assert (await client.delete(f"{base}/{locked['id']}")).status_code == 423
    await client.patch(f"{base}/{locked['id']}", json={"is_locked": False})
    assert (await client.delete(f"{base}/{locked['id']}")).status_code == 204


async def test_archive_invalidate_and_restore(client: AsyncClient) -> None:
    pid = await project(client, "Greenline")
    base = f"/api/projects/{pid}/memory"
    a, b = await memo(client, pid, title="A"), await memo(client, pid, title="B")
    archived = (await client.post(f"{base}/{a['id']}/archive")).json()
    assert archived["status"] == "archived" and archived["archived_at"]
    invalid = (await client.post(f"{base}/{b['id']}/invalidate")).json()
    assert invalid["status"] == "invalidated" and invalid["invalidated_at"]
    assert (await client.get(base)).json() == []
    assert len((await client.get(f"{base}?status=archived&status=invalidated")).json()) == 2
    assert (await client.post(f"{base}/{b['id']}/invalidate")).status_code == 409
    restored = (await client.post(f"{base}/{b['id']}/restore")).json()
    assert restored["status"] == "active" and restored["invalidated_at"] is None
    assert (await client.post(f"{base}/{restored['id']}/restore")).status_code == 409
    assert (await client.patch(f"{base}/{a['id']}", json={"title": ""})).status_code == 422
    assert (await client.patch(f"{base}/{a['id']}", json={})).status_code == 422
    assert (await client.patch(f"{base}/{a['id']}", json={"type": "rule"})).status_code == 422


async def test_memory_never_crosses_projects(client: AsyncClient, database_url: str) -> None:
    a, b = await project(client, "Project A"), await project(client, "Project B")
    mem_a = await memo(client, a, title="Party size = 5")
    mem_b = await memo(client, b, title="Party size = 4")
    task_b = (await client.post(f"/api/projects/{b}/tasks", json={"title": "B task"})).json()
    assert mem_a["human_id"] == mem_b["human_id"] == "DEC-001"

    assert (await client.get(f"/api/projects/{a}/memory/{mem_b['id']}")).status_code == 404
    assert (await client.get(f"/api/projects/{a}/memory/DEC-001")).json()["id"] == mem_a["id"]
    for method, path in (
        ("patch", f"/api/projects/{a}/memory/{mem_b['id']}"),
        ("post", f"/api/projects/{a}/memory/{mem_b['id']}/supersede"),
        ("post", f"/api/projects/{a}/memory/{mem_b['id']}/archive"),
        ("delete", f"/api/projects/{a}/memory/{mem_b['id']}"),
    ):
        response = await getattr(client, method)(
            path, **({"json": {"title": "x"}} if method != "delete" else {})
        )
        assert response.status_code == 404, path
    cross_task = await client.post(
        f"/api/projects/{a}/memory", json={"type": "note", "title": "x", "task_ids": [task_b["id"]]}
    )
    assert cross_task.status_code == 404
    assert [m["title"] for m in (await client.get(f"/api/projects/{a}/memory?q=party")).json()] == [
        "Party size = 5"
    ]

    db = sqlite3.connect(database_url.removeprefix("sqlite:///"))
    db.execute("PRAGMA foreign_keys=ON")
    for sql in (
        f"UPDATE memories SET supersedes_id='{mem_b['id']}' WHERE id='{mem_a['id']}'",
        "INSERT INTO memory_tasks (memory_id, task_id, project_id)"
        f" VALUES ('{mem_a['id']}', '{task_b['id']}', '{a}')",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(sql)
    db.close()


async def test_seeded_memory_and_downgrade(database_url: str) -> None:
    from app.seed import seed_projects

    seed_projects(database_url)
    async with app_client(database_url) as client:
        projects = {p["name"]: p["id"] for p in (await client.get("/api/projects")).json()}
        climb = (await client.get(f"/api/projects/{projects['Trailhead']}/memory")).json()
        assert {m["title"] for m in climb} >= {
            "Starting capacity is 6",
            "Old saves contain no camp_capacity",
        }
        soul = (await client.get(f"/api/projects/{projects['Starling']}/memory")).json()
        assert [m["title"] for m in soul] == ["Maximum party size is 4"]
        assert soul[0]["is_locked"] is True
    seed_projects(database_url)
    async with app_client(database_url) as client:
        assert len((await client.get(f"/api/projects/{projects['Starling']}/memory")).json()) == 1


async def test_known_issues_can_be_filtered_by_pending_and_resolved(client: AsyncClient) -> None:
    pid = await project(client, "Resolver")
    base = f"/api/projects/{pid}/memory"
    first = await memo(client, pid, type="bug", title="Crash on load")
    second = await memo(client, pid, type="bug", title="Wrong tooltip")
    assert first["is_resolved"] is False

    done = await client.patch(f"{base}/{second['id']}", json={"is_resolved": True})
    assert done.status_code == 200 and done.json()["is_resolved"] is True
    assert [m["id"] for m in (await client.get(f"{base}?type=bug&resolved=false")).json()] == [
        first["id"]
    ]
    assert [m["id"] for m in (await client.get(f"{base}?type=bug&resolved=true")).json()] == [
        second["id"]
    ]
    assert len((await client.get(f"{base}?type=bug")).json()) == 2
    reopened = await client.patch(f"{base}/{second['id']}", json={"is_resolved": False})
    assert reopened.json()["is_resolved"] is False
    assert (
        await client.patch(f"{base}/{first['id']}", json={"is_resolved": None})
    ).status_code == 422


async def test_resolved_issues_stay_out_of_context_packs_unless_named(client: AsyncClient) -> None:
    pid = await project(client, "Packs")
    base = f"/api/projects/{pid}/memory"
    bug = await memo(client, pid, type="bug", title="Crash on load", ai_visibility="always")
    await client.patch(f"{base}/{bug['id']}", json={"is_resolved": True})
    pending = await memo(client, pid, type="bug", title="Slow startup", ai_visibility="always")
    url = f"/api/projects/{pid}/context?detail=balanced"

    async def issue_titles(suffix: str = "") -> list[str]:
        response = await client.get(url + suffix)
        assert response.status_code == 200
        return [i["title"] for i in response.json()["items"] if i["section"] == "issues"]

    assert await issue_titles() == ["Slow startup"]
    assert sorted(await issue_titles(f"&include={bug['human_id']}")) == [
        "Crash on load",
        "Slow startup",
    ]
    assert pending["is_resolved"] is False


async def test_pending_note_is_saved_and_cleared(client: AsyncClient) -> None:
    pid = await project(client, "Notes")
    bug = await memo(client, pid, type="bug", title="Crash on load")
    assert bug["pending_note"] is None
    url = f"/api/projects/{pid}/memory/{bug['id']}"
    saved = await client.patch(url, json={"pending_note": "Still crashes on old saves"})
    assert saved.json()["pending_note"] == "Still crashes on old saves"
    cleared = await client.patch(url, json={"pending_note": None})
    assert cleared.status_code == 200 and cleared.json()["pending_note"] is None
    too_long = await client.patch(url, json={"pending_note": "x" * 2001})
    assert too_long.status_code == 422


async def test_known_issue_can_be_created_pending_or_resolved(client: AsyncClient) -> None:
    pid = await project(client, "Creator")
    pending = await memo(client, pid, type="bug", title="Pending one", is_resolved=False)
    resolved = await memo(client, pid, type="bug", title="Resolved one", is_resolved=True)
    assert pending["is_resolved"] is False and resolved["is_resolved"] is True


async def test_memory_filter_matches_non_ascii_text(client) -> None:
    project = (await client.post("/api/projects", json={"name": "Unicode"})).json()["id"]
    await client.post(
        f"/api/projects/{project}/memory", json={"type": "fact", "title": "Über Straße config"}
    )
    for query in ("über", "straße", "ÜBER"):
        found = (await client.get(f"/api/projects/{project}/memory", params={"q": query})).json()
        items = found["items"] if isinstance(found, dict) else found
        assert [m["title"] for m in items] == ["Über Straße config"], query

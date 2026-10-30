import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient

from app.core.resources import resource_path
from app.db.migrate import upgrade_database

pytestmark = pytest.mark.anyio


async def make_project(client: AsyncClient, name: str, **extra: object) -> str:
    response = await client.post("/api/projects", json={"name": name, **extra})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def make_task(client: AsyncClient, pid: str, **body: object) -> dict:
    response = await client.post(f"/api/projects/{pid}/tasks", json={"title": "Task", **body})
    assert response.status_code == 201, response.text
    return response.json()


async def test_task_ids_criteria_tags_and_milestones(client: AsyncClient) -> None:
    pid = await make_project(client, "Trailhead")
    milestone = (
        await client.post(f"/api/projects/{pid}/milestones", json={"name": "Demo 0.1.1"})
    ).json()

    first = await make_task(client, pid, title="Track capacity")
    assert first["human_id"] == "TRAI-001"
    prefixed = await make_project(client, "Starling", task_prefix="sk")
    assert (await make_task(client, prefixed))["human_id"] == "SK-001"
    renamed = await client.patch(f"/api/projects/{prefixed}", json={"task_prefix": "SOUL"})
    assert renamed.json()["task_prefix"] == "SOUL"
    assert (await make_task(client, prefixed))["human_id"] == "SOUL-001"
    camp = await make_task(
        client,
        pid,
        title="Camp Population Capacity",
        prefix="camp",
        milestone_id=milestone["id"],
        acceptance_criteria=["Track capacity", "Migrate old saves"],
        tags=["gameplay", "Gameplay", "save-system"],
    )
    assert camp["human_id"] == "CAMP-001"
    assert camp["milestone"]["name"] == "Demo 0.1.1"
    assert camp["tags"] == ["gameplay", "save-system"]
    assert [c["description"] for c in camp["acceptance_criteria"]] == [
        "Track capacity",
        "Migrate old saves",
    ]
    assert (await make_task(client, pid, prefix="CAMP"))["human_id"] == "CAMP-002"

    # Human IDs work as references, case-insensitively.
    url = f"/api/projects/{pid}/tasks/camp-001"
    criterion = camp["acceptance_criteria"][0]["id"]
    done = (await client.patch(f"{url}/criteria/{criterion}", json={"is_completed": True})).json()
    assert (done["criteria_completed"], done["criteria_total"]) == (1, 2)
    added = (await client.post(f"{url}/criteria", json={"description": "Show warning"})).json()
    last = added["acceptance_criteria"][-1]["id"]
    moved = (await client.patch(f"{url}/criteria/{last}", json={"sort_order": 0})).json()
    assert moved["acceptance_criteria"][0]["description"] == "Show warning"
    removed = (await client.delete(f"{url}/criteria/{last}")).json()
    assert [c["sort_order"] for c in removed["acceptance_criteria"]] == [0, 1]

    retagged = (await client.patch(url, json={"tags": ["demo"]})).json()
    assert retagged["tags"] == ["demo"]

    ms = (await client.get(f"/api/projects/{pid}/milestones")).json()
    assert (ms[0]["task_count"], ms[0]["completed_task_count"]) == (1, 0)


async def test_milestone_edit_reorder_archive_and_restore(client: AsyncClient) -> None:
    pid = await make_project(client, "Trailhead")
    other = await make_project(client, "Starling")
    base = f"/api/projects/{pid}/milestones"
    created = []
    for name in ("Prototype", "Demo", "Release"):
        response = await client.post(base, json={"name": name})
        assert response.status_code == 201, response.text
        created.append(response.json())
    await client.post(f"/api/projects/{other}/milestones", json={"name": "Other"})

    updated = await client.patch(
        f"{base}/{created[2]['id']}",
        json={
            "name": "Full Release",
            "description": "Ship the game",
            "target_date": "2026-12-01",
            "status": "active",
            "sort_order": 0,
        },
    )
    assert updated.status_code == 200, updated.text
    assert (
        updated.json()["name"],
        updated.json()["description"],
        updated.json()["target_date"],
        updated.json()["status"],
    ) == (
        "Full Release",
        "Ship the game",
        "2026-12-01",
        "active",
    )
    ordered = (await client.get(base)).json()
    assert [m["name"] for m in ordered] == ["Full Release", "Prototype", "Demo"]
    assert [m["sort_order"] for m in ordered] == [0, 1, 2]

    await client.patch(f"{base}/{created[1]['id']}", json={"status": "archived"})
    assert [m["name"] for m in (await client.get(base)).json()] == ["Full Release", "Prototype"]
    assert [m["name"] for m in (await client.get(f"{base}?include_archived=true")).json()] == [
        "Full Release",
        "Prototype",
        "Demo",
    ]
    restored = await client.patch(f"{base}/{created[1]['id']}", json={"status": "planned"})
    assert restored.json()["status"] == "planned"
    assert len((await client.get(base)).json()) == 3
    other_milestones = (await client.get(f"/api/projects/{other}/milestones")).json()
    assert [m["name"] for m in other_milestones] == ["Other"]


async def test_status_timestamps_board_moves_and_focus(client: AsyncClient) -> None:
    pid = await make_project(client, "Starling")
    a = await make_task(client, pid, title="A")
    b = await make_task(client, pid, title="B")
    c = await make_task(client, pid, title="C")
    base = f"/api/projects/{pid}/tasks"

    started = (await client.post(f"{base}/{a['id']}/start")).json()
    assert started["status"] == "in_progress" and started["started_at"] and started["is_focus"]
    project = (await client.get(f"/api/projects/{pid}")).json()
    assert project["current_focus_task_id"] == a["id"]

    # Drop C at the top of the To Do column; the column is renumbered.
    await client.post(f"{base}/{c['id']}/move", json={"status": "todo", "index": 0})
    todo = (await client.get(f"{base}?status=todo")).json()
    assert [t["title"] for t in todo] == ["C", "B"]
    assert [t["sort_order"] for t in todo] == [0, 1]

    completed = (await client.patch(f"{base}/{a['id']}", json={"status": "completed"})).json()
    assert completed["completed_at"] and not completed["is_focus"]
    assert (await client.get(f"/api/projects/{pid}")).json()["current_focus_task_id"] is None
    reopened = (await client.patch(f"{base}/{a['id']}", json={"status": "review"})).json()
    assert reopened["completed_at"] is None

    archived = (await client.patch(f"{base}/{b['id']}", json={"status": "archived"})).json()
    assert archived["archived_at"]
    assert b["id"] not in [t["id"] for t in (await client.get(base)).json()]
    focus = await client.put(f"/api/projects/{pid}/focus", json={"task": b["id"]})
    assert focus.status_code == 422

    assert (await client.put(f"/api/projects/{pid}/focus", json={"task": c["human_id"]})).json()[
        "current_focus_task_id"
    ] == c["id"]
    overview = (await client.get(f"/api/projects/{pid}/overview")).json()
    assert overview["focus_task"]["id"] == c["id"]
    assert overview["task_counts"] == {"review": 1, "todo": 1, "archived": 1}

    assert (await client.delete(f"{base}/{c['id']}")).status_code == 204
    assert (await client.get(f"/api/projects/{pid}")).json()["current_focus_task_id"] is None


async def test_relationships_normalize_and_reject_loops(client: AsyncClient) -> None:
    pid = await make_project(client, "Greenline")
    a, b, c = [await make_task(client, pid, title=t) for t in "ABC"]
    base = f"/api/projects/{pid}/tasks"

    # "A blocks B" is stored as "B depends on A" and shown from each side.
    from_a = (
        await client.post(
            f"{base}/{a['id']}/relationships", json={"type": "blocks", "target": b["human_id"]}
        )
    ).json()
    assert [(r["type"], r["task"]["id"]) for r in from_a["relationships"]] == [("blocks", b["id"])]
    from_b = (await client.get(f"{base}/{b['id']}")).json()
    assert [(r["type"], r["task"]["id"]) for r in from_b["relationships"]] == [
        ("depends_on", a["id"])
    ]
    assert from_b["is_blocked_by_open_dependency"] is True

    loop = await client.post(
        f"{base}/{a['id']}/relationships", json={"type": "depends_on", "target": b["id"]}
    )
    assert loop.status_code == 422
    duplicate = await client.post(
        f"{base}/{b['id']}/relationships", json={"type": "depends_on", "target": a["id"]}
    )
    assert duplicate.status_code == 409
    self_link = await client.post(
        f"{base}/{a['id']}/relationships", json={"type": "related_to", "target": a["id"]}
    )
    assert self_link.status_code == 422

    await client.post(f"{base}/{a['id']}/relationships", json={"type": "parent", "target": c["id"]})
    second_parent = await client.post(
        f"{base}/{c['id']}/relationships", json={"type": "child", "target": b["id"]}
    )
    assert second_parent.status_code == 409

    # Completing the dependency unblocks B.
    await client.patch(f"{base}/{a['id']}", json={"status": "completed"})
    assert (await client.get(f"{base}/{b['id']}")).json()["is_blocked_by_open_dependency"] is False

    rel_id = from_b["relationships"][0]["id"]
    after = (await client.delete(f"{base}/{b['id']}/relationships/{rel_id}")).json()
    assert after["relationships"] == []


async def test_projects_never_share_tasks(client: AsyncClient, database_url: str) -> None:
    a = await make_project(client, "Project A")
    b = await make_project(client, "Project B")
    milestone_b = (await client.post(f"/api/projects/{b}/milestones", json={"name": "B1"})).json()
    task_a = await make_task(client, a, title="Party size", prefix="DEC")
    task_b = await make_task(client, b, title="Party size", prefix="DEC")
    assert task_a["human_id"] == task_b["human_id"] == "DEC-001"

    # Same human ID resolves to each project's own task.
    assert (await client.get(f"/api/projects/{a}/tasks/DEC-001")).json()["id"] == task_a["id"]
    assert (await client.get(f"/api/projects/{b}/tasks/DEC-001")).json()["id"] == task_b["id"]
    # Another project's internal id is "not found", for reads and writes alike.
    assert (await client.get(f"/api/projects/{a}/tasks/{task_b['id']}")).status_code == 404
    patch = await client.patch(f"/api/projects/{a}/tasks/{task_b['id']}", json={"title": "x"})
    assert patch.status_code == 404
    cross_ms = await client.post(
        f"/api/projects/{a}/tasks", json={"title": "x", "milestone_id": milestone_b["id"]}
    )
    assert cross_ms.status_code == 404
    cross_rel = await client.post(
        f"/api/projects/{a}/tasks/{task_a['id']}/relationships",
        json={"type": "related_to", "target": task_b["id"]},
    )
    assert cross_rel.status_code == 404
    cross_focus = await client.put(f"/api/projects/{a}/focus", json={"task": task_b["id"]})
    assert cross_focus.status_code == 404
    assert [t["id"] for t in (await client.get(f"/api/projects/{a}/tasks")).json()] == [
        task_a["id"]
    ]

    workspace = (await client.get("/api/tasks")).json()
    assert {(t["project_name"], t["id"]) for t in workspace} == {
        ("Project A", task_a["id"]),
        ("Project B", task_b["id"]),
    }
    await client.post(f"/api/projects/{b}/archive")
    assert [t["project_name"] for t in (await client.get("/api/tasks")).json()] == ["Project A"]

    # The database itself rejects cross-project links, even bypassing the services.
    db = sqlite3.connect(database_url.removeprefix("sqlite:///"))
    db.execute("PRAGMA foreign_keys=ON")
    for sql in (
        f"UPDATE tasks SET milestone_id='{milestone_b['id']}' WHERE id='{task_a['id']}'",
        f"UPDATE projects SET current_focus_task_id='{task_b['id']}' WHERE id='{a}'",
        "INSERT INTO task_relationships (id, project_id, source_task_id, target_task_id, type,"
        f" created_at) VALUES ('r', '{a}', '{task_a['id']}', '{task_b['id']}', 'related_to',"
        " '2026-01-01')",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(sql)
    db.close()


def test_migration_keeps_phase1_projects_and_constraints(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'old.db'}"
    config = Config(str(resource_path("backend/alembic.ini")))
    config.attributes["database_url"] = url
    command.upgrade(config, "0001_projects")
    db = sqlite3.connect(tmp_path / "old.db")
    db.execute(
        "INSERT INTO projects (id, name, name_key, slug, status, created_at, updated_at)"
        " VALUES ('p1', 'Old', 'old', 'old', 'active', '2026-01-01', '2026-01-01')"
    )
    db.commit()
    db.close()

    upgrade_database(url)
    db = sqlite3.connect(tmp_path / "old.db")
    assert db.execute(
        "SELECT name, task_prefix FROM projects WHERE kind = 'project'"
    ).fetchall() == [("Old", None)]
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE projects SET status='bogus'")
    db.close()

    command.downgrade(config, "0001_projects")
    db = sqlite3.connect(tmp_path / "old.db")
    assert db.execute("SELECT name FROM projects").fetchall() == [("Old",)]
    db.close()

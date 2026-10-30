"""Phase 4 checkpoint and activity API behavior."""

import sqlite3

import pytest
from httpx import AsyncClient

from app.db.session import make_engine, make_session_factory
from app.schemas.memory import MemoryCreate, MemoryUpdate
from app.services.activity import ActivityService
from app.services.memory import MemoryService

pytestmark = pytest.mark.anyio


async def project(client: AsyncClient, name: str) -> str:
    response = await client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def task(client: AsyncClient, project_id: str, title: str) -> dict:
    response = await client.post(f"/api/projects/{project_id}/tasks", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()


async def checkpoint(client: AsyncClient, project_id: str, **body: object) -> dict:
    response = await client.post(
        f"/api/projects/{project_id}/checkpoints", json={"title": "Work session", **body}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_checkpoint_create_latest_edit_and_task_deletion_preserves_history(
    client: AsyncClient,
) -> None:
    pid = await project(client, "Trailhead")
    current_task = await task(client, pid, "Camp capacity")
    base = f"/api/projects/{pid}/checkpoints"
    assert (await client.get(f"{base}/latest")).status_code == 404

    first = await checkpoint(
        client,
        pid,
        task_id=current_task["human_id"],
        title="Capacity draft",
        summary="Implemented calculation",
        completed_work="- Added capacity calculation",
        remaining_work="- Test old saves",
        problems="Old saves have no capacity",
        next_steps="Add migration fallback",
        agent="Codex",
        git_commit="abcdef0123456789",
    )
    assert first["task_id"] == current_task["id"]
    assert first["task"]["human_id"] == current_task["human_id"]
    assert first["summary"] == "Implemented calculation"
    assert first["created_at"].endswith("Z")
    project_wide = await checkpoint(client, pid, title="Milestone review")
    latest_task = await checkpoint(
        client, pid, task_id=current_task["id"], title="Capacity verification"
    )
    assert (await client.get(f"{base}/latest")).json()["id"] == latest_task["id"]
    assert (await client.get(f"{base}/latest?task={current_task['human_id']}")).json()[
        "id"
    ] == latest_task["id"]
    assert [row["id"] for row in (await client.get(base)).json()] == [
        latest_task["id"],
        project_wide["id"],
        first["id"],
    ]
    assert [
        row["id"]
        for row in (await client.get(f"{base}?task={current_task['id']}&limit=1&offset=1")).json()
    ] == [first["id"]]

    updated = await client.patch(
        f"{base}/{first['id']}", json={"title": "Capacity tested", "task_id": None}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["task_id"] is None
    assert updated.json()["updated_at"] >= first["updated_at"]
    assert (await client.patch(f"{base}/{first['id']}", json={})).status_code == 422
    assert (await client.patch(f"{base}/{first['id']}", json={"summary": None})).status_code == 422

    events = (await client.get(f"/api/projects/{pid}/activity?entity_type=checkpoint")).json()
    assert [event["event_type"] for event in events] == [
        "CHECKPOINT_UPDATED",
        "CHECKPOINT_CREATED",
        "CHECKPOINT_CREATED",
        "CHECKPOINT_CREATED",
    ]
    assert events[0]["metadata"]["changed_fields"] == ["task_id", "title"]
    assert events[0]["project_name"] == "Trailhead"
    task_events = (
        await client.get(f"/api/projects/{pid}/activity?task={current_task['human_id']}")
    ).json()
    assert [
        event["entity_id"] for event in task_events if event["entity_type"] == "checkpoint"
    ] == [
        latest_task["id"],
        first["id"],
    ]

    # The live task link clears on hard deletion; checkpoint text and audit references remain.
    deleted = await client.delete(f"/api/projects/{pid}/tasks/{current_task['id']}")
    assert deleted.status_code == 204, deleted.text
    persisted = (await client.get(f"{base}/{latest_task['id']}")).json()
    assert persisted["title"] == "Capacity verification" and persisted["task_id"] is None
    created_events = (
        await client.get(f"/api/projects/{pid}/activity?event_type=CHECKPOINT_CREATED")
    ).json()
    assert len(created_events) == 3
    assert created_events[0]["entity_id"] == latest_task["id"]
    assert created_events[0]["metadata"]["task_human_id"] == current_task["human_id"]


async def test_project_isolation_filters_and_atomic_agent_attribution(
    client: AsyncClient, database_url: str
) -> None:
    a, b = await project(client, "Project A"), await project(client, "Project B")
    task_b = await task(client, b, "Task B")
    cp_a = await checkpoint(client, a, title="A checkpoint")
    cp_b = await checkpoint(client, b, title="B checkpoint", task_id=task_b["id"])

    assert (
        await client.post(
            f"/api/projects/{a}/checkpoints",
            json={"title": "Cross project", "task_id": task_b["id"]},
        )
    ).status_code == 404
    assert (await client.get(f"/api/projects/{a}/checkpoints/{cp_b['id']}")).status_code == 404
    assert (
        await client.patch(
            f"/api/projects/{a}/checkpoints/{cp_a['id']}", json={"task_id": task_b["id"]}
        )
    ).status_code == 404
    assert [c["id"] for c in (await client.get(f"/api/projects/{a}/checkpoints")).json()] == [
        cp_a["id"]
    ]

    engine = make_engine(database_url)
    try:
        session_factory = make_session_factory(engine)
        with session_factory() as session:
            service = ActivityService(session)
            service.record(
                a,
                "AGENT_SESSION_STARTED",
                actor_type="codex",
                actor_name="Codex",
                entity_type="project",
                entity_id=a,
                metadata={"phase": 4},
            )
            session.commit()
        with session_factory() as session:
            ActivityService(session).record(
                a,
                "AGENT_SESSION_FINISHED",
                actor_type="codex",
                metadata={"rolled_back": True},
            )
            session.rollback()
    finally:
        engine.dispose()

    codex = (await client.get("/api/activity?actor_type=codex")).json()
    assert len(codex) == 1
    assert codex[0]["project_id"] == a and codex[0]["project_name"] == "Project A"
    assert codex[0]["actor_name"] == "Codex" and codex[0]["metadata"] == {"phase": 4}
    assert codex[0]["timestamp"].endswith("Z")
    assert (await client.get("/api/activity?actor_type=unknown")).status_code == 422
    assert (await client.get("/api/activity?limit=0")).status_code == 422

    workspace = (await client.get(f"/api/activity?project_id={b}&entity_type=checkpoint")).json()
    assert [e["entity_id"] for e in workspace] == [cp_b["id"]]
    assert [
        e["entity_id"]
        for e in (await client.get("/api/activity?entity_type=checkpoint&limit=1&offset=1")).json()
    ] == [cp_a["id"]]
    assert (await client.get(f"/api/projects/{a}/activity?event_type=CHECKPOINT_CREATED")).json()[
        0
    ]["entity_id"] == cp_a["id"]
    assert (await client.get("/api/activity?project_id=missing")).status_code == 404

    db = sqlite3.connect(database_url.removeprefix("sqlite:///"))
    db.execute("PRAGMA foreign_keys=ON")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE checkpoints SET task_id=?, task_project_id=? WHERE id=?",
            (task_b["id"], b, cp_a["id"]),
        )
    db.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO activity_events "
            "(id, project_id, task_id, task_project_id, event_type, actor_type, "
            "metadata, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("cross-event", a, task_b["id"], b, "TEST_EVENT", "human", "{}", "2026-01-01"),
        )
    db.close()


async def test_existing_writes_emit_durable_activity_with_correct_actors(
    client: AsyncClient, database_url: str
) -> None:
    pid = await project(client, "Audit project")
    created_project = (
        await client.get(f"/api/projects/{pid}/activity?event_type=PROJECT_CREATED")
    ).json()
    assert len(created_project) == 1
    assert created_project[0]["actor_type"] == "human"
    assert created_project[0]["entity_id"] == pid
    assert created_project[0]["metadata"]["name"] == "Audit project"

    current_task = await task(client, pid, "Implement capacity")
    task_url = f"/api/projects/{pid}/tasks/{current_task['id']}"
    for status in ("in_progress", "blocked", "completed"):
        response = await client.patch(task_url, json={"status": status})
        assert response.status_code == 200, response.text
    task_events = (await client.get(f"/api/projects/{pid}/activity?entity_type=task")).json()
    assert [event["event_type"] for event in task_events] == [
        "TASK_COMPLETED",
        "TASK_BLOCKED",
        "TASK_STARTED",
        "TASK_CREATED",
    ]
    assert all(event["actor_type"] == "human" for event in task_events)
    assert task_events[0]["metadata"]["human_id"] == current_task["human_id"]

    human_memory_response = await client.post(
        f"/api/projects/{pid}/memory", json={"type": "decision", "title": "Capacity is six"}
    )
    assert human_memory_response.status_code == 201, human_memory_response.text
    human_memory = human_memory_response.json()
    memory_url = f"/api/projects/{pid}/memory/{human_memory['id']}"
    locked = await client.patch(memory_url, json={"is_locked": True})
    assert locked.status_code == 200, locked.text

    engine = make_engine(database_url)
    try:
        with make_session_factory(engine)() as session:
            service = MemoryService(session)
            agent_memory = service.create(
                pid, MemoryCreate(type="note", title="Claude's investigation"), actor="claude"
            )
            service.update(
                pid,
                agent_memory.id,
                MemoryUpdate(content="Codex verified the result"),
                actor="codex",
            )
        before_rejection = len(
            (await client.get(f"/api/projects/{pid}/activity?entity_type=memory")).json()
        )
        with make_session_factory(engine)() as session:
            with pytest.raises(Exception) as caught:
                MemoryService(session).update(
                    pid,
                    human_memory["id"],
                    MemoryUpdate(content="silent rewrite"),
                    actor="codex",
                )
            assert getattr(caught.value, "status_code", None) == 423
        assert (
            len((await client.get(f"/api/projects/{pid}/activity?entity_type=memory")).json())
            == before_rejection
        )
    finally:
        engine.dispose()

    claude = (await client.get(f"/api/activity?project_id={pid}&actor_type=claude")).json()
    codex = (await client.get(f"/api/activity?project_id={pid}&actor_type=codex")).json()
    assert len(claude) == len(codex) == 1
    assert claude[0]["event_type"] == "MEMORY_CREATED"
    assert codex[0]["event_type"] == "MEMORY_UPDATED"
    assert claude[0]["entity_id"] == codex[0]["entity_id"] == agent_memory.id
    assert claude[0]["metadata"]["human_id"] == agent_memory.human_id
    locked_events = (
        await client.get(f"/api/projects/{pid}/activity?event_type=MEMORY_LOCKED")
    ).json()
    assert len(locked_events) == 1 and locked_events[0]["entity_id"] == human_memory["id"]

    deleted_memory = await client.delete(f"/api/projects/{pid}/memory/{agent_memory.id}")
    assert deleted_memory.status_code == 204, deleted_memory.text
    assert (await client.get(f"/api/projects/{pid}/memory/{agent_memory.id}")).status_code == 404
    memory_deletions = (
        await client.get(f"/api/projects/{pid}/activity?event_type=MEMORY_DELETED")
    ).json()
    assert len(memory_deletions) == 1
    assert memory_deletions[0]["entity_id"] == agent_memory.id
    assert memory_deletions[0]["metadata"]["title"] == "Claude's investigation"

    deleted_task = await client.delete(task_url)
    assert deleted_task.status_code == 204, deleted_task.text
    assert (await client.get(task_url)).status_code == 404
    task_deletions = (
        await client.get(f"/api/projects/{pid}/activity?event_type=TASK_DELETED")
    ).json()
    assert len(task_deletions) == 1
    assert task_deletions[0]["entity_id"] == current_task["id"]
    assert task_deletions[0]["task_id"] is None
    assert task_deletions[0]["metadata"]["human_id"] == current_task["human_id"]

    archived = await client.post(f"/api/projects/{pid}/archive")
    assert archived.status_code == 200, archived.text
    restored = await client.patch(f"/api/projects/{pid}", json={"status": "active"})
    assert restored.status_code == 200, restored.text
    project_events = (await client.get(f"/api/projects/{pid}/activity?entity_type=project")).json()
    assert [event["event_type"] for event in project_events] == [
        "PROJECT_RESTORED",
        "PROJECT_ARCHIVED",
        "PROJECT_CREATED",
    ]

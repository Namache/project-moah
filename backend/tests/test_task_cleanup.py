from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.session import make_engine, make_session_factory
from app.models.graph import DataLink
from app.models.image import Image
from app.models.task import Task
from app.services.task_cleanup import delete_old_done_tasks
from tests.test_images import attach, png

pytestmark = pytest.mark.anyio


async def _setup(client) -> tuple[str, dict, dict]:
    pid = (await client.post("/api/projects", json={"name": "Cleanup"})).json()["id"]
    base = f"/api/projects/{pid}/tasks"
    done = (await client.post(base, json={"title": "Ship it"})).json()
    open_task = (await client.post(base, json={"title": "Still going"})).json()
    await client.patch(f"{base}/{done['id']}", json={"status": "completed"})
    return pid, done, open_task


def _session(database_url):
    return make_session_factory(make_engine(database_url))()


async def test_off_by_default_keeps_done_tasks(client, database_url) -> None:
    assert (await client.get("/api/settings/tasks")).json()["auto_delete_done"] is False
    _, done, _ = await _setup(client)
    with _session(database_url) as session:
        later = datetime.now(UTC) + timedelta(days=60)
        assert delete_old_done_tasks(session, now=later) == []
        assert session.get(Task, done["id"]) is not None


async def test_deletes_after_two_weeks_and_keeps_activity(client, database_url) -> None:
    pid, done, open_task = await _setup(client)
    url = f"/api/projects/{pid}/tasks/{done['id']}"
    assert (await attach(client, url, png())).status_code == 201
    turned_on = (await client.patch("/api/settings/tasks", json={"auto_delete_done": True})).json()
    assert turned_on["auto_delete_done"] is True and turned_on["auto_delete_done_since"]
    # Saving "on" again does not restart the clock.
    again = (await client.patch("/api/settings/tasks", json={"auto_delete_done": True})).json()
    assert again["auto_delete_done_since"] == turned_on["auto_delete_done_since"]

    with _session(database_url) as session:
        session.add(
            DataLink(
                project_id=pid,
                source_kind="task",
                source_id=done["id"],
                target_kind="task",
                target_id=open_task["id"],
                relationship="related_to",
            )
        )
        session.commit()
        now = datetime.now(UTC)
        assert delete_old_done_tasks(session, now=now + timedelta(days=13)) == []
        assert delete_old_done_tasks(session, now=now + timedelta(days=15)) == [done["human_id"]]
        assert session.get(Task, done["id"]) is None
        assert session.get(Task, open_task["id"]) is not None
        assert session.scalars(select(DataLink)).all() == []
        assert session.scalars(select(Image)).all() == []

    events = (await client.get(f"/api/projects/{pid}/activity")).json()
    kinds = [e["event_type"] for e in events]
    assert {"TASK_CREATED", "TASK_COMPLETED", "TASK_DELETED"} <= set(kinds)
    deleted = next(e for e in events if e["event_type"] == "TASK_DELETED")
    assert deleted["actor_type"] == "system" and deleted["actor_name"] == "moah"
    assert deleted["metadata"]["title"] == "Ship it"
    assert deleted["metadata"]["reason"] == "done_for_two_weeks"


async def test_clock_starts_when_turned_on(client, database_url) -> None:
    _, done, _ = await _setup(client)
    with _session(database_url) as session:
        task = session.get(Task, done["id"])
        task.completed_at = datetime.now(UTC) - timedelta(days=100)
        session.commit()
    await client.patch("/api/settings/tasks", json={"auto_delete_done": True})
    with _session(database_url) as session:
        now = datetime.now(UTC)
        # Done for 100 days already, but the setting is new: nothing vanishes today.
        assert delete_old_done_tasks(session, now=now) == []
        assert delete_old_done_tasks(session, now=now + timedelta(days=15)) == [done["human_id"]]


async def test_reopened_task_is_kept(client, database_url) -> None:
    pid, done, _ = await _setup(client)
    await client.patch(f"/api/projects/{pid}/tasks/{done['id']}", json={"status": "review"})
    await client.patch("/api/settings/tasks", json={"auto_delete_done": True})
    with _session(database_url) as session:
        assert delete_old_done_tasks(session, now=datetime.now(UTC) + timedelta(days=30)) == []

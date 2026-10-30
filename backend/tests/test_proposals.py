import pytest
from httpx import AsyncClient

from app.db.session import make_engine, make_session_factory
from app.schemas.proposal import ProposalCreate
from app.services.activity import acting_as
from app.services.proposals import ProposalService

pytestmark = pytest.mark.anyio


async def project(client: AsyncClient, name: str) -> str:
    return (await client.post("/api/projects", json={"name": name})).json()["id"]


async def propose(
    client: AsyncClient, pid: str, kind: str, target: str | None = None, **payload: object
) -> dict:
    body = {
        "proposal_type": kind,
        "target": target,
        "payload": payload,
        "reason": "Because",
        "agent": "codex",
    }
    response = await client.post(f"/api/projects/{pid}/proposals", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def test_locked_memory_change_waits_for_review_then_applies(client: AsyncClient) -> None:
    pid = await project(client, "Trailhead")
    base = f"/api/projects/{pid}"
    locked = (
        await client.post(
            f"{base}/memory",
            json={
                "type": "decision",
                "title": "Base camp capacity",
                "content": "6",
                "is_locked": True,
            },
        )
    ).json()

    proposal = await propose(client, pid, "update_memory", locked["human_id"], content="8")
    assert (
        proposal["human_id"] == "PROP-001"
        and proposal["status"] == "pending"
        and proposal["agent"] == "codex"
    )
    assert (
        proposal["target_locked"] is True
        and proposal["target_label"] == "DEC-001 Base camp capacity"
    )
    assert proposal["changes"] == ["Content: 6 → 8"]
    assert (await client.get(f"{base}/memory/{locked['id']}")).json()["content"] == "6"  # untouched

    accepted = (await client.post(f"{base}/proposals/{proposal['id']}/accept")).json()
    assert accepted["status"] == "accepted" and accepted["reviewed_at"]
    after = (await client.get(f"{base}/memory/{locked['id']}")).json()
    assert after["content"] == "8" and after["is_locked"] is True  # still locked afterwards
    assert (await client.post(f"{base}/proposals/{proposal['id']}/accept")).status_code == 409
    assert (await client.post(f"{base}/proposals/{proposal['id']}/reject")).status_code == 409
    kinds = [
        (e["event_type"], e["actor_type"]) for e in (await client.get(f"{base}/activity")).json()
    ]
    assert ("PROPOSAL_CREATED", "codex") in kinds and ("PROPOSAL_ACCEPTED", "human") in kinds


async def test_edit_and_accept_reject_and_replacement(client: AsyncClient) -> None:
    pid = await project(client, "Starling")
    base = f"/api/projects/{pid}"
    memory = (
        await client.post(
            f"{base}/memory", json={"type": "fact", "title": "Engine", "content": "Godot 3"}
        )
    ).json()
    edited_source = await propose(
        client, pid, "update_memory", memory["human_id"], content="Godot 4"
    )
    edited = (
        await client.post(
            f"{base}/proposals/{edited_source['id']}/accept",
            json={"payload": {"content": "Godot 4.3"}, "note": "Tweaked"},
        )
    ).json()
    assert (
        edited["applied_payload"] == {"content": "Godot 4.3"} and edited["review_note"] == "Tweaked"
    )
    assert (await client.get(f"{base}/memory/{memory['id']}")).json()["content"] == "Godot 4.3"

    rejected_source = await propose(
        client, pid, "update_memory", memory["human_id"], content="Unity"
    )
    rejected = (
        await client.post(f"{base}/proposals/{rejected_source['id']}/reject", json={"note": "No"})
    ).json()
    assert rejected["status"] == "rejected" and rejected["review_note"] == "No"
    assert (await client.get(f"{base}/memory/{memory['id']}")).json()["content"] == "Godot 4.3"
    assert [p["human_id"] for p in (await client.get(f"{base}/proposals")).json()] == []
    assert (
        len(
            (
                await client.get(f"{base}/proposals", params={"status": ["accepted", "rejected"]})
            ).json()
        )
        == 2
    )

    replace = await propose(
        client,
        pid,
        "supersede_memory",
        memory["human_id"],
        title="Engine is Godot 4.3",
        content="Confirmed",
    )
    assert replace["changes"][0].startswith("Replace")
    await client.post(f"{base}/proposals/{replace['id']}/accept")
    assert (await client.get(f"{base}/memory/{memory['id']}")).json()["status"] == "superseded"
    assert [m["title"] for m in (await client.get(f"{base}/memory")).json()] == [
        "Engine is Godot 4.3"
    ]


async def test_every_proposal_type_applies(client: AsyncClient, tmp_path) -> None:
    pid = await project(client, "Trailhead")
    base = f"/api/projects/{pid}"
    task = (
        await client.post(
            f"{base}/tasks",
            json={"title": "Camp", "prefix": "CAMP", "acceptance_criteria": ["A", "B"]},
        )
    ).json()
    await client.post(f"{base}/tasks/{task['id']}/start")
    rule = (
        await client.post(f"{base}/memory", json={"type": "rule", "title": "Use signals"})
    ).json()

    async def accept(proposal: dict) -> dict:
        response = await client.post(f"{base}/proposals/{proposal['id']}/accept")
        assert response.status_code == 200, response.text
        return response.json()

    await accept(
        await propose(
            client,
            pid,
            "create_memory",
            type="decision",
            title="Party of 4",
            content="x",
            task_ids=[task["human_id"]],
        )
    )
    await accept(
        await propose(client, pid, "create_bug", title="Old saves broken", type="note")
    )  # type is forced to bug
    bug = next(
        m for m in (await client.get(f"{base}/memory")).json() if m["title"] == "Old saves broken"
    )
    assert bug["type"] == "bug"
    await accept(
        await propose(
            client, pid, "add_acceptance_criterion", task["human_id"], description="Show warning"
        )
    )
    await accept(
        await propose(
            client,
            pid,
            "update_task",
            task["human_id"],
            next_action="Migrate saves",
            priority="high",
        )
    )
    after = (await client.get(f"{base}/tasks/{task['id']}")).json()
    assert (after["next_action"], after["priority"], after["criteria_total"]) == (
        "Migrate saves",
        "high",
        3,
    )

    plain = await propose(client, pid, "complete_task", task["human_id"])
    assert "Requirements: 0 of 3 done now, unchanged by this" in plain["changes"]
    await accept(plain)
    done = (await client.get(f"{base}/tasks/{task['id']}")).json()
    assert (
        done["status"] == "completed" and done["criteria_completed"] == 0
    )  # criteria stay as evidence

    other = (
        await client.post(f"{base}/tasks", json={"title": "Other", "acceptance_criteria": ["A"]})
    ).json()
    await accept(
        await propose(client, pid, "complete_task", other["human_id"], complete_all_criteria=True)
    )
    assert (await client.get(f"{base}/tasks/{other['id']}")).json()["criteria_completed"] == 1

    (tmp_path / "camp.gd").write_text("x")
    file_one = await propose(
        client,
        pid,
        "associate_file",
        path="camp.gd",
        purpose="Camp state",
        task_ids=[task["human_id"]],
    )
    await accept(file_one)
    await accept(
        await propose(
            client,
            pid,
            "associate_file",
            path="camp.gd",
            memory_ids=[rule["human_id"]],
            summary="More",
        )
    )
    notes = (await client.get(f"{base}/files/by-path", params={"path": "camp.gd"})).json()
    assert notes["purpose"] == "Camp state" and notes["summary"] == "More"
    assert [t["human_id"] for t in notes["tasks"]] == ["CAMP-001"] and [
        m["human_id"] for m in notes["memories"]
    ] == ["RULE-001"]


async def test_invalid_stale_and_cross_project_proposals(
    client: AsyncClient, database_url: str
) -> None:
    a, b = await project(client, "A"), await project(client, "B")
    mem_a = (
        await client.post(f"/api/projects/{a}/memory", json={"type": "rule", "title": "A rule"})
    ).json()
    mem_b = (
        await client.post(f"/api/projects/{b}/memory", json={"type": "rule", "title": "B rule"})
    ).json()
    task_b = (await client.post(f"/api/projects/{b}/tasks", json={"title": "B task"})).json()
    url = f"/api/projects/{a}/proposals"

    def body(**kw: object) -> dict:
        return {
            "proposal_type": "update_memory",
            "target": mem_a["human_id"],
            "payload": {"content": "x"},
            "reason": "r",
            **kw,
        }

    assert (
        await client.post(url, json=body(target=mem_b["id"]))
    ).status_code == 404  # another project's record
    assert (
        await client.post(url, json=body(payload={"content": "x", "task_ids": [task_b["id"]]}))
    ).status_code == 404
    assert (await client.post(url, json=body(target=None))).status_code == 422
    assert (await client.post(url, json=body(payload={"nonsense": 1}))).status_code == 422
    assert (await client.post(url, json=body(payload={"title": ""}))).status_code == 422
    assert (await client.post(url, json=body(proposal_type="delete_everything"))).status_code == 422
    assert (
        await client.post(
            url, json=body(proposal_type="complete_task", target="NOPE-1", payload={})
        )
    ).status_code == 404

    proposal = (await client.post(url, json=body())).json()
    assert (await client.get(f"/api/projects/{b}/proposals/{proposal['id']}")).status_code == 404
    assert (
        await client.post(f"/api/projects/{b}/proposals/{proposal['id']}/accept")
    ).status_code == 404

    # The target is archived before review: accepting fails, changes nothing, and says why.
    await client.post(f"/api/projects/{a}/memory/{mem_a['id']}/archive")
    failed = await client.post(f"{url}/{proposal['id']}/accept")
    assert failed.status_code == 409
    again = (await client.get(f"{url}/{proposal['id']}")).json()
    assert again["status"] == "pending" and "archived" in again["error"]
    good = await propose(client, a, "create_memory", type="note", title="Fine")
    result = (await client.post(f"{url}/accept-all")).json()
    assert [p["id"] for p in result["accepted"]] == [good["id"]] and [
        p["id"] for p in result["failed"]
    ] == [proposal["id"]]

    pending = (await client.get("/api/proposals/pending")).json()
    assert pending["total"] == 1 and pending["by_project"] == {a: 1}
    await client.post(f"/api/projects/{a}/archive")
    assert (await client.get("/api/proposals/pending")).json()["total"] == 0


async def test_service_attributes_agent_actions(client: AsyncClient, database_url: str) -> None:
    pid = await project(client, "Attributed")
    engine = make_engine(database_url)
    try:
        with make_session_factory(engine)() as session, acting_as("claude", "claude"):
            ProposalService(session).create(
                pid,
                ProposalCreate(
                    proposal_type="create_memory",
                    payload={"type": "note", "title": "n"},
                    reason="r",
                ),
                agent="claude",
            )
    finally:
        engine.dispose()
    events = (await client.get(f"/api/projects/{pid}/activity")).json()
    created = next(e for e in events if e["event_type"] == "PROPOSAL_CREATED")
    assert (created["actor_type"], created["actor_name"]) == ("claude", "claude")


async def test_completing_a_task_settles_its_waiting_completion_proposal(
    client: AsyncClient,
) -> None:
    pid = await project(client, "Desk Critters")
    base = f"/api/projects/{pid}"
    task = (
        await client.post(f"{base}/tasks", json={"title": "Remove Ranch jobs", "status": "review"})
    ).json()
    plain = await propose(client, pid, "complete_task", task["human_id"])
    with_criteria = await propose(
        client, pid, "complete_task", task["human_id"], complete_all_criteria=True
    )
    update = await propose(client, pid, "update_task", task["human_id"], priority="high")

    # The person completes the task on the board instead of in Review.
    moved = await client.post(
        f"{base}/tasks/{task['id']}/move", json={"status": "completed", "index": 0}
    )
    assert moved.status_code == 200, moved.text
    plain = (await client.get(f"{base}/proposals/{plain['id']}")).json()
    assert plain["status"] == "accepted"
    assert plain["review_note"] == "The task was completed directly."

    # One that also ticks every requirement still waits, and accepting it now works.
    assert (await client.get(f"{base}/proposals/{with_criteria['id']}")).json()["status"] == (
        "pending"
    )
    response = await client.post(f"{base}/proposals/{with_criteria['id']}/accept")
    assert response.status_code == 200, response.text
    assert (await client.get(f"{base}/tasks/{task['id']}")).json()["status"] == "completed"

    # Changing a completed task still cannot apply, and says why.
    response = await client.post(f"{base}/proposals/{update['id']}/accept")
    assert response.status_code == 409
    assert "already completed" in response.json()["detail"]


async def test_a_completion_proposal_for_a_completed_task_can_still_be_accepted(
    client: AsyncClient, database_url: str
) -> None:
    """Proposals left waiting before completing a task settled them (2026-10-18 and earlier)."""
    pid = await project(client, "Desk Critters")
    base = f"/api/projects/{pid}"
    task = (await client.post(f"{base}/tasks", json={"title": "Remove Ranch jobs"})).json()
    stale = await propose(client, pid, "complete_task", task["human_id"])
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        from app.models.task import Task

        session.get(Task, task["id"]).status = "completed"  # completed the old way
        session.commit()

    response = await client.post(f"{base}/proposals/{stale['id']}/accept")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted"
    pending = (await client.get(f"{base}/proposals", params={"status": "pending"})).json()
    assert pending == []

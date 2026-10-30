"""Links made by an agent's writes: what it names, what its text names, and its session's task.

The reported problem (2026-10-18): records agents wrote in a session stayed unlinked in the Brain.
These tests drive the real MCP server the way an agent does and check the links that result.
"""

import pytest
from httpx import AsyncClient

from app.db.session import make_engine, make_session_factory
from app.mcp.linking import IDLE_SECONDS, SessionTask
from app.services.context import ContextService
from app.services.graph import GraphService
from app.services.retrieval import RetrievalService
from tests.conftest import app_client
from tests.test_mcp import agent, call

pytestmark = pytest.mark.anyio


async def post(client: AsyncClient, url: str, **body: object) -> dict:
    response = await client.post(url, json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()


async def seed(client: AsyncClient) -> dict:
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    base = f"/api/projects/{pid}"
    task = await post(client, f"{base}/tasks", title="Camp capacity", prefix="CAMP")
    decision = await post(
        client, f"{base}/memory", type="decision", title="Capacity is 6", task_ids=[task["id"]]
    )
    warning = await post(client, f"{base}/memory", type="warning", title="Saves are fragile")
    local_rule = await post(client, f"{base}/memory", type="rule", title="Small scenes")
    global_rule = await post(
        client, "/api/projects/global/memory", type="rule", title="Ask before building"
    )
    return {
        "pid": pid,
        "task": task["human_id"],
        "decision": decision["human_id"],
        "warning": warning["human_id"],
        "local_rule": local_rule["human_id"],
        "global_rule": global_rule["human_id"],
    }


def links_of(result: dict) -> dict[str, dict]:
    return {x["node"]: x for x in result["links"]}


async def test_what_an_agent_writes_in_a_session_joins_the_brain(database_url: str) -> None:
    async with app_client(database_url) as client:
        s = await seed(client)
    pid, camp = s["pid"], s["task"]
    async with agent(database_url, "codex") as session:
        failed, pack = await call(session, "brain_context_pack", task=camp, project=pid)
        assert not failed
        assert 'brain_retrieval_feedback(retrieval="R-' in pack
        assert f"This session's task is {camp}" in pack
        failed, state = await call(session, "brain_project_state", project=pid)
        assert not failed and state["session_task"] == camp

        # A task named in related is one of the memory's tasks; a typo or an unknown
        # relationship is reported, and the memory is saved anyway.
        failed, bug = await call(
            session,
            "brain_create_memory",
            type="bug",
            title="Tents vanish on reload",
            content=f"Started after the global {s['global_rule']} cleanup.",
            project=pid,
            related=[camp, "NOPE-999"],
            links=[f"caused_by {s['decision']}", f"blames {s['decision']}"],
        )
        assert not failed, bug
        assert bug["tasks"] == [camp]
        assert bug["links"] == [f"caused_by {s['decision']}"]
        assert [x.split(":")[0] for x in bug["not_linked"]] == [
            "NOPE-999",
            f"blames {s['decision']}",
        ]
        assert "not a known relationship" in bug["not_linked"][1]
        assert bug["references_found"] == [f"{s['global_rule']} (global)"]

        # No task named: the session's task is the link.
        failed, fact = await call(
            session, "brain_create_memory", type="fact", title="Tents live in slot 2", project=pid
        )
        assert not failed and fact["links"] == [f"relates_to {camp} (this session's task)"]
        failed, seen = await call(session, "brain_links", node=fact["created"], project=pid)
        session_link = links_of(seen)[f"task:{camp}"]
        assert session_link["status"] == "active" and session_link["confidence"] == 0.6
        assert f"written while working on {camp} in the same session" in session_link["why"]

        # Edits are linked too, and links can be added to locked memory without editing it.
        failed, edited = await call(
            session,
            "brain_update_memory",
            memory=fact["created"],
            content=f"Moved there because of {bug['created']}; {s['local_rule']} still applies.",
            project=pid,
        )
        assert not failed and set(edited["references_found"]) == {
            bug["created"],
            s["local_rule"],
        }
        failed, explained = await call(
            session,
            "brain_update_memory",
            memory=s["decision"],
            links=[f"explains {fact['created']}"],
            project=pid,
        )
        assert not failed and explained["links"] == [f"explains {fact['created']}"]

        # A replacement keeps every link of the record it replaces.
        failed, newer = await call(
            session,
            "brain_supersede_memory",
            memory=fact["created"],
            title="Tents live in save slot 2",
            project=pid,
        )
        assert not failed
        failed, seen = await call(session, "brain_links", node=newer["created"], project=pid)
        kept = links_of(seen)
        assert {f"task:{camp}", f"memory:{bug['created']}", f"memory:{s['decision']}"} <= set(kept)
        assert "carried over from" in kept[f"task:{camp}"]["why"]

        failed, follow_up = await call(
            session,
            "brain_create_task",
            title="Persist tents",
            project=pid,
            links=[f"blocked_by {bug['created']}"],
        )
        assert not failed
        assert follow_up["links"] == [
            f"blocked_by {bug['created']}",
            f"relates_to {camp} (this session's task)",
        ]

        # A checkpoint reports on the session's task and links what it names.
        failed, checkpoint = await call(
            session,
            "brain_create_checkpoint",
            title="Tents saved",
            summary=f"Fixed the reload. {s['warning']} bit us again.",
            project=pid,
        )
        assert not failed and checkpoint["task"] == camp
        assert checkpoint["links"] == [f"{camp} references {s['warning']}"]

        # The next pack for the task finds what this session wrote.
        failed, pack = await call(session, "brain_context_pack", task=camp, project=pid)
        assert not failed
        for ref in (bug["created"], newer["created"], s["warning"]):
            assert ref in pack, ref

        # Setting a task in progress makes it the session's task.
        failed, started = await call(
            session,
            "brain_update_task",
            task=follow_up["created"],
            status="in_progress",
            project=pid,
        )
        assert not failed and started["status"] == "in_progress"
        failed, state = await call(session, "brain_project_state", project=pid)
        assert state["session_task"] == follow_up["created"]

        # A new session starts with no task of its own.
        failed, _ = await call(session, "brain_brief", project=pid)
        assert not failed
        failed, state = await call(session, "brain_project_state", project=pid)
        assert state["session_task"] is None
        failed, loose = await call(
            session, "brain_create_memory", type="note", title="Unrelated note", project=pid
        )
        assert not failed and loose["links"] == []


async def test_a_search_pack_does_not_claim_the_focus_task(database_url: str) -> None:
    async with app_client(database_url) as client:
        s = await seed(client)
        focus = await client.put(f"/api/projects/{s['pid']}/focus", json={"task": s["task"]})
        assert focus.status_code == 200, focus.text
    async with agent(database_url) as session:
        failed, pack = await call(session, "brain_context_pack", query="tents", project=s["pid"])
        assert not failed and "This session's task" not in pack
        failed, state = await call(session, "brain_project_state", project=s["pid"])
        assert state["session_task"] is None
        # Without a query, the pack is for the focus task, and that is the work.
        failed, pack = await call(session, "brain_context_pack", project=s["pid"])
        assert not failed and f"This session's task is {s['task']}" in pack


def test_session_task_ends_after_a_long_pause() -> None:
    now = [0.0]
    working = SessionTask(clock=lambda: now[0])
    working.set("p1", "t1")
    now[0] += IDLE_SECONDS - 1
    working.tick()
    assert working._tasks == {"p1": "t1"}
    now[0] += IDLE_SECONDS + 1
    working.tick()
    assert working._tasks == {}


def test_links_are_written_as_relationship_then_target() -> None:
    parse = GraphService.parse_link
    assert parse("caused_by DEC-002") == ("caused_by", "DEC-002")
    assert parse("caused_by: DEC-002") == ("caused_by", "DEC-002")
    assert parse("depends on CAMP-3") == ("depends_on", "CAMP-3")
    assert parse("must not depend on CAMP-3") == ("must_not_depend_on", "CAMP-3")
    assert parse("uses file:src/my save.gd") == ("uses", "file:src/my save.gd")
    assert parse("DEC-002") == ("relates_to", "DEC-002")
    assert parse("shelf:Save System") == ("relates_to", "shelf:Save System")
    with pytest.raises(Exception, match="not a known relationship"):
        parse("blames DEC-002")


async def test_records_that_help_together_confirm_the_guess_between_them(
    client: AsyncClient, database_url: str
) -> None:
    pid = (await post(client, "/api/projects", name="Dragons"))["id"]
    base = f"/api/projects/{pid}"
    task = await post(client, f"{base}/tasks", title="Hatchery timers")
    a = await post(
        client, f"{base}/memory", type="fact", title="Egg timer ticks", task_ids=[task["id"]]
    )
    b = await post(client, f"{base}/memory", type="fact", title="Nest heat", task_ids=[task["id"]])
    guess = await post(
        client,
        f"{base}/links",
        source=a["human_id"],
        relationship="relates_to",
        target=b["human_id"],
        status="candidate",
        confidence=0.4,
    )
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        pack = ContextService(session).build(
            pid, task=task["human_id"], record_for="claude", explore=False
        )
        result = RetrievalService(session).feedback(
            pid,
            pack.retrieval_id,
            useful=[a["human_id"], b["human_id"]],
            not_useful=[],
            actor="claude",
        )
    assert result["links_changed"] >= 1
    links = (await client.get(f"{base}/links", params={"node": a["human_id"]})).json()["links"]
    [confirmed] = [x for x in links if x["id"] == guess["id"]]
    # Active, and trusted enough to be walked: strength 0.5 x 0.4 would stay under the floor.
    assert confirmed["status"] == "active" and confirmed["confidence"] >= 0.6


async def test_the_app_links_what_checkpoints_and_replacements_name(client: AsyncClient) -> None:
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    base = f"/api/projects/{pid}"
    task = await post(client, f"{base}/tasks", title="Camp capacity", prefix="CAMP")
    warning = await post(client, f"{base}/memory", type="warning", title="Saves are fragile")
    note = await post(client, f"{base}/memory", type="note", title="Tents")
    before = (await client.get("/api/brain/version")).json()["version"]

    await post(
        client,
        f"{base}/checkpoints",
        title="Camps",
        summary=f"{warning['human_id']} again",
        task_id=task["id"],
    )
    links = (await client.get(f"{base}/links", params={"node": task["human_id"]})).json()["links"]
    assert any(x["node"]["label"] == warning["human_id"] for x in links)

    newer = await post(
        client,
        f"{base}/memory/{note['human_id']}/supersede",
        title="Tents",
        content=f"See {task['human_id']}",
    )
    links = (await client.get(f"{base}/links", params={"node": newer["human_id"]})).json()["links"]
    assert any(x["node"]["label"] == task["human_id"] for x in links)
    assert (await client.get("/api/brain/version")).json()["version"] > before


async def test_a_proposal_naming_a_missing_record_is_refused_at_once(client: AsyncClient) -> None:
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    response = await client.post(
        f"/api/projects/{pid}/proposals",
        json={
            "proposal_type": "create_memory",
            "payload": {"type": "fact", "title": "Tents", "related": ["FACT-404"]},
            "reason": "test",
        },
    )
    assert response.status_code == 404 and "FACT-404" in response.text


async def test_feedback_on_a_record_linked_by_its_tasks_field_is_saved(
    client: AsyncClient, database_url: str
) -> None:
    """A built-in link learning for the first time used to crash feedback (2026-10-18)."""
    pid = (await post(client, "/api/projects", name="Dragons"))["id"]
    base = f"/api/projects/{pid}"
    task = await post(client, f"{base}/tasks", title="Hatchery timers")
    fact = await post(
        client, f"{base}/memory", type="fact", title="Egg timer ticks", task_ids=[task["id"]]
    )
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        pack = ContextService(session).build(
            pid, task=task["human_id"], record_for="codex", explore=False
        )
        result = RetrievalService(session).feedback(
            pid, pack.retrieval_id, useful=[fact["human_id"]], not_useful=[], actor="codex"
        )
    assert result["links_changed"] == 1


async def test_a_strong_link_lifts_and_explains_a_record_that_also_matches_by_words(
    client: AsyncClient, database_url: str
) -> None:
    """Scorecard gap (2026-10-17): a linked record that also shared words with the task was
    ranked by the word match alone and explained as "matches the task"."""
    pid = (await post(client, "/api/projects", name="Trailhead"))["id"]
    base = f"/api/projects/{pid}"
    task = await post(client, f"{base}/tasks", title="Tent saving breaks")
    linked = await post(client, f"{base}/memory", type="fact", title="Tent saving uses slot 2")
    await post(
        client,
        f"{base}/links",
        source=task["human_id"],
        relationship="explained_by",
        target=linked["human_id"],
        strength=0.9,
    )
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        pack = ContextService(session).build(pid, task=task["human_id"])
    [item] = [i for i in pack.items if i.title == linked["title"]]
    assert item.reason == f"via {task['human_id']} → explained by → {linked['human_id']}"

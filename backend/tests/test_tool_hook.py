"""Every question and report remembers the chat that wrote it, and a reply in that chat settles
every question that chat asked (services/chat_questions.py), for Claude Code and Codex alike.

The world is a small harbor-map project the way a working session leaves it: global and project
rules, a decision and a warning on a shelf tree, an orchestrator task in progress with two
checkpoints of history, and the open sub-tasks it hands out. The agent's calls go through the
real MCP server; the hook then gets exactly what that server answered."""

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from httpx import AsyncClient

from tests.conftest import app_client
from tests.test_chat_questions import SESSION, database, run_hook
from tests.test_mcp import agent

pytestmark = pytest.mark.anyio

OTHER = "5e0a7d3c-91b4-4f2e-8c6a-b27d4e9f1a38"  # another chat, made up
CODEX = "019a7c2e-5b1f-7c3a-8e4d-2f6b9a1c0d37"  # a Codex thread id, made up
TILES = "Should the map export use PNG or WebP tiles?"
TILES_IN_CHAT = f"I asked in Review about the tile format.\n\n{TILES}"


async def post(client: AsyncClient, url: str, **body: object) -> dict:
    response = await client.post(url, json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()


async def sandbox(client: AsyncClient, tmp_path: Path) -> dict:
    root = tmp_path / "harbor-lights"
    (root / "src").mkdir(parents=True)
    pid = (await post(client, "/api/projects", name="Harbor Lights", root_path=str(root)))["id"]
    await post(
        client,
        "/api/projects/global/memory",
        type="rule",
        title="Ask before adding dependencies",
        content="Show the package and why before installing anything new.",
        importance="high",
    )
    for title in ("Every screen works offline", "Release notes name every visible change"):
        await post(client, f"/api/projects/{pid}/memory", type="rule", title=title, content=title)
    tiles = await post(
        client,
        f"/api/projects/{pid}/memory",
        type="decision",
        title="Map tiles are cut at 256 pixels",
        content="Every export slices the map into 256 pixel tiles.",
    )
    seams = await post(
        client,
        f"/api/projects/{pid}/memory",
        type="warning",
        title="Tile seams show at odd zoom levels",
        content="Round the offset, never the tile size.",
    )
    for name, parent in (("Delivery", None), ("Map exports", "Delivery")):
        await post(client, f"/api/projects/{pid}/shelves", name=name, parent=parent)
    for memory in (tiles, seams):
        await post(
            client,
            f"/api/projects/{pid}/shelves/Map exports/members",
            node=f"memory:{memory['id']}",
        )
    base = f"/api/projects/{pid}/tasks"
    orchestrator = await post(
        client,
        base,
        title="Ship the 2.0 harbor map release",
        prefix="HARB",
        acceptance_criteria=["Every export opens offline", "Release notes are written"],
    )
    sub = await post(client, base, title="Choose the tile format for map export")
    notes = await post(client, base, title="Write the release notes")
    for task in (orchestrator, sub, notes):
        await client.post(f"{base}/{task['id']}/start")
    await client.post(
        f"{base}/{orchestrator['id']}/relationships", json={"type": "parent", "target": sub["id"]}
    )
    for title, done in (
        ("Export pipeline sliced", "Tiles are cut and named by zoom level"),
        ("Offline check passed", "Every screen opens without a connection"),
    ):
        await post(
            client,
            f"/api/projects/{pid}/checkpoints",
            task_id=orchestrator["id"],
            title=title,
            completed_work=done,
            remaining_work="Pick the tile format and write the release notes",
        )
    return {
        "pid": pid,
        "root": root,
        "orchestrator": orchestrator["human_id"],
        "sub": sub["human_id"],
        "notes": notes["human_id"],
    }


def tool_call(tool: str, arguments: dict, response: object, server: str = "project-brain", **more):
    """What an agent hands its PostToolUse hook after a Moah tool call."""
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": f"mcp__{server}__{tool}",
        "tool_input": arguments,
        "tool_response": response,
        **more,
    }


async def call(mcp, tool: str, **arguments: object) -> dict:
    """Call a tool on the real MCP server and return the result as the agent hands it to its
    hook (an MCP result: content, structuredContent, isError)."""
    result = await mcp.call_tool(tool, {"project": "harbor-lights", **arguments})
    assert not result.is_error, result.content
    return result.model_dump(mode="json", by_alias=True, exclude_none=True)


def rounds(database_url: str, ref: str) -> list[tuple[str, str, str | None]]:
    """(kind, status, chat) of each round of a task's reviews, oldest first."""
    from app.models.review import TaskReview
    from app.models.task import Task

    with database(database_url) as session:
        task = session.query(Task).filter(Task.human_id == ref).one()
        found = session.query(TaskReview).filter(TaskReview.task_id == task.id)
        return [(r.kind, r.status, r.session_id) for r in found.order_by(TaskReview.round)]


def worked_on(database_url: str, session_id: str, agent_name: str = "claude") -> list[str]:
    """The tasks the session was recorded on, oldest first."""
    from app.models.agent_session import AgentSessionEvent
    from app.models.task import Task

    with database(database_url) as session:
        found = (
            session.query(Task.human_id)
            .join(AgentSessionEvent, AgentSessionEvent.task_id == Task.id)
            .filter(
                AgentSessionEvent.agent == agent_name,
                AgentSessionEvent.session_id == session_id,
                AgentSessionEvent.source.in_(("task", "hook_task")),
            )
            .order_by(AgentSessionEvent.id)
        )
        return [ref for (ref,) in found]


def task_sources(database_url: str, session_id: str) -> list[tuple[str, str]]:
    """(source, task) of each task event the session has, oldest first."""
    from app.models.agent_session import AgentSessionEvent
    from app.models.task import Task

    with database(database_url) as session:
        found = (
            session.query(AgentSessionEvent.source, Task.human_id)
            .join(Task, Task.id == AgentSessionEvent.task_id)
            .filter(AgentSessionEvent.session_id == session_id)
            .order_by(AgentSessionEvent.id)
        )
        return [tuple(row) for row in found]


def status_of(database_url: str, ref: str) -> str:
    from app.models.task import Task

    with database(database_url) as session:
        return session.query(Task.status).filter(Task.human_id == ref).scalar()


def answered(database_url: str, ref: str) -> tuple[str, str | None, str | None]:
    """(state, the person's reply, where they gave it) of the task's newest round."""
    from app.models.review import TaskReview
    from app.models.task import Task

    with database(database_url) as session:
        task = session.query(Task).filter(Task.human_id == ref).one()
        newest = (
            session.query(TaskReview)
            .filter(TaskReview.task_id == task.id)
            .order_by(TaskReview.round.desc())
            .first()
        )
        return newest.status, newest.comment, newest.moved_to


async def test_a_question_asked_through_moah_is_stamped_with_its_chat_and_not_asked_twice(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    async with app_client(database_url) as client:
        w = await sandbox(client, tmp_path)
    root, orchestrator, sub = str(w["root"]), w["orchestrator"], w["sub"]
    run_hook(
        monkeypatch,
        capsys,
        database_url,
        "prompt",
        {"prompt": "Let's get the harbor map release out.", "cwd": root},
    )
    # The desktop app's shared server is told no session id: only the hook knows the chat.
    async with agent(database_url, "claude") as mcp:
        pack = await call(mcp, "brain_context_pack", task=orchestrator)
        run_hook(
            monkeypatch,
            capsys,
            database_url,
            "tool",
            tool_call("brain_context_pack", {"task": orchestrator}, pack, cwd=root),
        )
        asked = await call(
            mcp, "brain_ask_person", task=sub, question=TILES, options=["PNG", "WebP"]
        )
        assert rounds(database_url, sub) == [("question", "pending", None)]
        # Another chat reading the same task writes nothing to Review, so it stamps nothing.
        run_hook(
            monkeypatch,
            capsys,
            database_url,
            "tool",
            tool_call("brain_context_pack", {"task": sub}, pack, cwd=root, session_id=OTHER),
        )
        assert rounds(database_url, sub) == [("question", "pending", None)]
        assert worked_on(database_url, OTHER) == [sub]
        call_to_hook = tool_call(
            "brain_ask_person", {"task": sub, "question": TILES, "project": "harbor-lights"}, asked
        )
        run_hook(monkeypatch, capsys, database_url, "tool", {**call_to_hook, "cwd": root})
        assert rounds(database_url, sub) == [("question", "pending", SESSION)]
        assert worked_on(database_url, SESSION) == [orchestrator, sub]
        # The same call again, as a retry does, records and stamps nothing new.
        run_hook(monkeypatch, capsys, database_url, "tool", {**call_to_hook, "cwd": root})
        assert worked_on(database_url, SESSION) == [orchestrator, sub]
        # The agent goes back to the orchestrator task, whose pack becomes the session's task.
        run_hook(
            monkeypatch,
            capsys,
            database_url,
            "tool",
            tool_call("brain_context_pack", {"task": orchestrator}, pack, cwd=root),
        )
        assert worked_on(database_url, SESSION) == [orchestrator, sub, orchestrator]

    # It ends its turn repeating the question in the chat. The session's task is the
    # orchestrator now, which has no question waiting, but the chat already asked this turn.
    run_hook(monkeypatch, capsys, database_url, "stop", {"last_assistant_message": TILES_IN_CHAT})
    assert rounds(database_url, orchestrator) == []
    assert rounds(database_url, sub) == [("question", "pending", SESSION)]
    assert status_of(database_url, sub) == "blocked"


async def test_a_reply_in_the_chat_settles_every_question_that_chat_asked_on_any_task(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    async with app_client(database_url) as client:
        w = await sandbox(client, tmp_path)
    root, orchestrator, sub = str(w["root"]), w["orchestrator"], w["sub"]
    run_hook(monkeypatch, capsys, database_url, "prompt", {"prompt": "Go on.", "cwd": root})
    # The orchestrator asks about its own task through a server that knows its session...
    async with agent(database_url, "claude", "--session-id", SESSION) as mcp:
        await call(mcp, "brain_ask_person", task=orchestrator, question="Ship on Friday?")
    assert rounds(database_url, orchestrator) == [("question", "pending", SESSION)]
    # ...and about its sub-task through one that does not (the desktop app's), then moves on.
    async with agent(database_url, "claude") as mcp:
        asked = await call(mcp, "brain_ask_person", task=sub, question=TILES)
        pack = await call(mcp, "brain_context_pack", task=orchestrator)
    for tool, arguments, response in (
        ("brain_ask_person", {"task": sub, "question": TILES}, asked),
        ("brain_context_pack", {"task": orchestrator}, pack),
    ):
        run_hook(
            monkeypatch,
            capsys,
            database_url,
            "tool",
            tool_call(tool, {**arguments, "project": "harbor-lights"}, response, cwd=root),
        )
    assert rounds(database_url, sub) == [("question", "pending", SESSION)]
    assert worked_on(database_url, SESSION)[-1] == orchestrator  # the sub-task is not the session's

    run_hook(
        monkeypatch,
        capsys,
        database_url,
        "prompt",
        {"prompt": "Friday is fine, and use WebP.", "cwd": root},
    )
    for ref in (orchestrator, sub):
        assert rounds(database_url, ref) == [("question", "answered", SESSION)]
        assert answered(database_url, ref) == ("answered", "Friday is fine, and use WebP.", "chat")
        assert status_of(database_url, ref) == "in_progress"


async def test_a_reply_leaves_other_chats_questions_and_reports_alone(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.models.agent_session import AgentSessionEvent
    from app.models.task import Task

    async with app_client(database_url) as client:
        w = await sandbox(client, tmp_path)
    root, sub, notes = str(w["root"]), w["sub"], w["notes"]
    # Another chat asked a question about the sub-task; this chat handed over its notes task (a
    # report, which a chat reply does not decide) and now works on the sub-task.
    async with agent(database_url, "claude", "--session-id", OTHER) as mcp:
        await call(mcp, "brain_ask_person", task=sub, question=TILES)
    async with agent(database_url, "claude", "--session-id", SESSION) as mcp:
        await call(
            mcp,
            "brain_submit_review",
            task=notes,
            summary="The release notes list every visible change.",
            done=["Wrote the notes"],
        )
    with database(database_url) as session:
        task = session.query(Task).filter(Task.human_id == sub).one()
        session.add(
            AgentSessionEvent(
                agent="claude",
                session_id=SESSION,
                project_id=task.project_id,
                task_id=task.id,
                source="task",
            )
        )
        session.commit()
    assert rounds(database_url, sub) == [("question", "pending", OTHER)]
    assert rounds(database_url, notes) == [("work", "pending", SESSION)]

    run_hook(monkeypatch, capsys, database_url, "prompt", {"prompt": "WebP.", "cwd": root})
    assert rounds(database_url, sub) == [("question", "pending", OTHER)]
    assert rounds(database_url, notes) == [("work", "pending", SESSION)]
    assert status_of(database_url, sub) == "blocked" and status_of(database_url, notes) == "review"

    # The chat that asked settles its own question, and the other chat's reply does too.
    run_hook(
        monkeypatch,
        capsys,
        database_url,
        "prompt",
        {"session_id": OTHER, "prompt": "PNG, the other chat knows.", "cwd": root},
    )
    assert answered(database_url, sub) == ("answered", "PNG, the other chat knows.", "chat")
    assert rounds(database_url, notes) == [("work", "pending", SESSION)]


async def test_a_question_that_cannot_be_settled_does_not_undo_or_block_the_others(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    """Three questions of one chat wait; settling the second fails half way through. The first
    stays settled, the second is left as it was (not half answered), the third is still settled,
    the prompt is still recorded, and the failure reaches the local error log, not the agent."""
    from app.models.agent_session import AgentSessionEvent
    from app.services.tasks import TaskService

    monkeypatch.setenv("PROJECT_BRAIN_ERROR_LOG_DIR", str(tmp_path / "logs"))
    async with app_client(database_url) as client:
        w = await sandbox(client, tmp_path)
    root, orchestrator, sub, notes = str(w["root"]), w["orchestrator"], w["sub"], w["notes"]
    async with agent(database_url, "claude", "--session-id", SESSION) as mcp:
        for ref in (orchestrator, sub, notes):  # the oldest round is settled first
            await call(mcp, "brain_ask_person", task=ref, question=f"About {ref}: go ahead?")

    updated = TaskService.update
    attempts: list[str] = []

    def failing(self, project_id, task_ref, payload, note=None):
        attempts.append(task_ref)
        if task_ref == failing_id[0]:
            raise RuntimeError("the task could not be saved")
        return updated(self, project_id, task_ref, payload, note)

    from app.models.task import Task

    with database(database_url) as session:
        failing_id = [session.query(Task.id).filter(Task.human_id == sub).scalar()]
    monkeypatch.setattr(TaskService, "update", failing)
    run_hook(monkeypatch, capsys, database_url, "prompt", {"prompt": "Yes.", "cwd": root})
    monkeypatch.setattr(TaskService, "update", updated)

    assert len(attempts) == 3 and attempts[1] == failing_id[0]  # tried in the order they were asked
    assert rounds(database_url, orchestrator) == [("question", "answered", SESSION)]
    assert rounds(database_url, sub) == [("question", "pending", SESSION)]  # not half answered
    assert rounds(database_url, notes) == [("question", "answered", SESSION)]
    assert status_of(database_url, sub) == "blocked"
    assert answered(database_url, sub) == ("pending", None, None)
    with database(database_url) as session:
        prompts = session.query(AgentSessionEvent).filter_by(source="prompt")
        assert prompts.count() == 1
    logged = (tmp_path / "logs" / "errors-mcp.log").read_text(encoding="utf-8")
    assert "prompt hook: RuntimeError" in logged

    # The next message settles it, as nothing was lost.
    run_hook(monkeypatch, capsys, database_url, "prompt", {"prompt": "Yes, still.", "cwd": root})
    assert answered(database_url, sub) == ("answered", "Yes, still.", "chat")


async def test_an_older_question_without_a_chat_is_settled_only_on_the_sessions_own_task(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.models.agent_session import AgentSessionEvent
    from app.models.task import Task
    from app.schemas.review import AskPerson
    from app.services.activity import acting_as
    from app.services.reviews import ReviewService

    async with app_client(database_url) as client:
        w = await sandbox(client, tmp_path)
    root, orchestrator, sub = str(w["root"]), w["orchestrator"], w["sub"]
    # Asked before reviews remembered their chat: no session id on either.
    with database(database_url) as session, acting_as("claude", "claude"):
        pid = session.query(Task).filter(Task.human_id == orchestrator).one().project_id
        for ref, question in ((orchestrator, "Ship on Friday?"), (sub, TILES)):
            ReviewService(session).ask(pid, ref, AskPerson(question=question), "claude")
        own = session.query(Task).filter(Task.human_id == orchestrator).one()
        session.add(
            AgentSessionEvent(
                agent="claude", session_id=SESSION, project_id=pid, task_id=own.id, source="task"
            )
        )
        session.commit()
    assert rounds(database_url, orchestrator) == [("question", "pending", None)]

    run_hook(monkeypatch, capsys, database_url, "prompt", {"prompt": "Friday.", "cwd": root})
    assert rounds(database_url, orchestrator) == [("question", "answered", None)]
    assert answered(database_url, orchestrator) == ("answered", "Friday.", "chat")
    assert rounds(database_url, sub) == [("question", "pending", None)]  # not this chat's task


async def test_codex_chats_are_stamped_and_settled_the_same_way(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    async with app_client(database_url) as client:
        w = await sandbox(client, tmp_path)
    root, orchestrator, sub = str(w["root"]), w["orchestrator"], w["sub"]
    chat = {"session_id": CODEX, "cwd": root}
    run_hook(
        monkeypatch,
        capsys,
        database_url,
        "prompt",
        {"prompt": "Let's get the harbor map release out.", **chat},
        agent="codex",
    )
    async with agent(database_url, "codex") as mcp:
        pack = await call(mcp, "brain_context_pack", task=orchestrator)
        asked = await call(mcp, "brain_ask_person", task=sub, question=TILES)
    # Codex names the server with an underscore or a hyphen, and gives the hook the MCP result.
    for tool, arguments, response, server in (
        ("brain_context_pack", {"task": orchestrator}, pack, "project_moah"),
        ("brain_ask_person", {"task": sub, "question": TILES}, asked, "project-moah"),
        ("brain_context_pack", {"task": orchestrator}, pack, "project_moah"),
    ):
        run_hook(
            monkeypatch,
            capsys,
            database_url,
            "tool",
            tool_call(
                tool,
                {**arguments, "project": "harbor-lights"},
                response,
                server=server,
                turn_id="turn-1",
                **chat,
            ),
            agent="codex",
        )
    assert rounds(database_url, sub) == [("question", "pending", CODEX)]
    assert worked_on(database_url, CODEX, "codex") == [orchestrator, sub, orchestrator]
    assert worked_on(database_url, SESSION) == []  # nothing leaks into a Claude chat

    run_hook(
        monkeypatch,
        capsys,
        database_url,
        "stop",
        {"last_assistant_message": TILES_IN_CHAT, "turn_id": "turn-1", **chat},
        agent="codex",
    )
    assert rounds(database_url, orchestrator) == []
    assert rounds(database_url, sub) == [("question", "pending", CODEX)]

    # A Claude chat's reply never touches a Codex chat's question.
    run_hook(monkeypatch, capsys, database_url, "prompt", {"prompt": "PNG.", "cwd": root})
    assert rounds(database_url, sub) == [("question", "pending", CODEX)]
    run_hook(
        monkeypatch,
        capsys,
        database_url,
        "prompt",
        {"prompt": "WebP, please.", **chat},
        agent="codex",
    )
    assert answered(database_url, sub) == ("answered", "WebP, please.", "chat")


async def test_the_mcp_server_stamps_the_reviews_it_writes_with_its_session(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    async with app_client(database_url) as client:
        w = await sandbox(client, tmp_path)
    orchestrator, sub, notes = w["orchestrator"], w["sub"], w["notes"]
    async with agent(database_url, "claude", "--session-id", SESSION) as mcp:
        await call(mcp, "brain_ask_person", task=sub, question=TILES)
        await call(
            mcp,
            "brain_submit_review",
            task=notes,
            summary="The release notes list every visible change.",
            done=["Wrote the notes"],
        )
        await call(
            mcp,
            "brain_create_checkpoint",
            task=orchestrator,
            title="Ready for your go-ahead on the release",
            waiting_for_person=True,
        )
    assert rounds(database_url, sub) == [("question", "pending", SESSION)]
    assert rounds(database_url, notes) == [("work", "pending", SESSION)]
    assert rounds(database_url, orchestrator) == [("question", "pending", SESSION)]

    # A later note from another chat updates the wait, and the wait is that chat's now. A server
    # that does not know its session leaves it empty for the hook to fill, never the old chat's.
    async with agent(database_url, "claude", "--session-id", OTHER) as mcp:
        await call(
            mcp,
            "brain_create_checkpoint",
            task=orchestrator,
            title="Still ready for your go-ahead",
            waiting_for_person=True,
        )
    assert rounds(database_url, orchestrator) == [("question", "pending", OTHER)]
    async with agent(database_url, "claude") as mcp:
        await call(
            mcp,
            "brain_create_checkpoint",
            task=orchestrator,
            title="Go-ahead needed, third note",
            waiting_for_person=True,
        )
    assert rounds(database_url, orchestrator) == [("question", "pending", None)]

    # A note that waits for the person is a question like any other: the chat's reply settles it.
    async with agent(database_url, "claude", "--session-id", OTHER) as mcp:
        await call(
            mcp,
            "brain_create_checkpoint",
            task=orchestrator,
            title="Go-ahead needed, fourth note",
            waiting_for_person=True,
        )
    run_hook(
        monkeypatch,
        capsys,
        database_url,
        "prompt",
        {"session_id": OTHER, "prompt": "Go ahead.", "cwd": str(w["root"])},
    )
    assert answered(database_url, orchestrator) == ("answered", "Go ahead.", "chat")
    assert rounds(database_url, sub) == [("question", "pending", SESSION)]  # another chat's


async def test_the_tool_hook_records_under_its_own_source_and_adds_what_the_server_has(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    async with app_client(database_url) as client:
        w = await sandbox(client, tmp_path)
    root, orchestrator, sub = str(w["root"]), w["orchestrator"], w["sub"]
    # A server that knows its session records the task itself (source task)...
    async with agent(database_url, "claude", "--session-id", SESSION) as mcp:
        pack = await call(mcp, "brain_context_pack", task=orchestrator)
    assert task_sources(database_url, SESSION) == [("task", orchestrator)]
    # ...so the hook, handed the same call, writes nothing. A task only the hook saw is its own.
    for task in (orchestrator, sub):
        run_hook(
            monkeypatch,
            capsys,
            database_url,
            "tool",
            tool_call("brain_context_pack", {"task": task}, pack, cwd=root),
        )
    assert task_sources(database_url, SESSION) == [("task", orchestrator), ("hook_task", sub)]


async def test_a_chat_known_only_through_the_tool_hook_gets_its_closing_question_caught(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    """The desktop app's shared server never learns the chat: the session's task is what the tool
    hook saw, and the Stop hook files the chat's closing question on it."""
    async with app_client(database_url) as client:
        w = await sandbox(client, tmp_path)
    root, notes = str(w["root"]), w["notes"]
    run_hook(monkeypatch, capsys, database_url, "prompt", {"prompt": "Go on.", "cwd": root})
    async with agent(database_url, "claude") as mcp:
        pack = await call(mcp, "brain_context_pack", task=notes)
    run_hook(
        monkeypatch,
        capsys,
        database_url,
        "tool",
        tool_call("brain_context_pack", {"task": notes}, pack, cwd=root),
    )
    assert task_sources(database_url, SESSION) == [("hook_task", notes)]
    message = "I drafted the release notes.\n\nShould the tone be formal or friendly?"
    run_hook(monkeypatch, capsys, database_url, "stop", {"last_assistant_message": message})
    assert rounds(database_url, notes) == [("question", "pending", SESSION)]
    run_hook(monkeypatch, capsys, database_url, "prompt", {"prompt": "Friendly.", "cwd": root})
    assert answered(database_url, notes) == ("answered", "Friendly.", "chat")


async def test_the_follow_up_a_stop_hook_starts_is_recorded_as_a_hook_task(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.models.agent_session import AgentSessionEvent
    from app.models.task import Task
    from tests.test_reviews import submit_review

    async with app_client(database_url) as client:
        w = await sandbox(client, tmp_path)
    pid, sub = w["pid"], w["sub"]
    with database(database_url) as session:
        task = session.query(Task).filter(Task.human_id == sub).one()
        session.add(  # the MCP server recorded the session's task
            AgentSessionEvent(
                agent="claude", session_id=SESSION, project_id=pid, task_id=task.id, source="task"
            )
        )
        session.commit()
    submit_review(database_url, pid, sub)
    async with app_client(database_url) as client:
        url = f"/api/projects/{pid}/tasks/{sub}/review/decision"
        assert (await client.post(url, json={"verdict": "accept"})).status_code == 200
    run_hook(
        monkeypatch, capsys, database_url, "prompt", {"prompt": "Go on.", "cwd": str(w["root"])}
    )
    run_hook(monkeypatch, capsys, database_url, "stop", {"last_assistant_message": TILES_IN_CHAT})
    [(first, _), (second, follow_up)] = task_sources(database_url, SESSION)
    assert (first, second) == ("task", "hook_task") and follow_up != sub
    assert rounds(database_url, follow_up) == [("question", "pending", SESSION)]


# ---- which calls name the session's task, in the shapes agents hand them ----------------------


def shapes(result: dict) -> list[object]:
    """One tool result as Claude Code and Codex may give it to a hook."""
    text = json.dumps(result, indent=2)
    blocks = [{"type": "text", "text": text}]
    return [
        result,
        text,
        blocks,
        {"content": blocks, "isError": False},
        {"content": blocks, "structuredContent": {"result": result}, "isError": False},
        {"structuredContent": result},
    ]


def named_cases(w: dict) -> list[tuple[str, dict, dict, str | None]]:
    """(tool, its arguments, its result, the task the session works on after it, or None): the
    same conditions the MCP server sets the session's task under (mcp/tools/*.py)."""
    orch, sub, notes = w["orchestrator"], w["sub"], w["notes"]
    started = {"status": "in_progress"}
    return [
        ("brain_create_task", started, {"created": notes, "status": "in_progress"}, notes),
        ("brain_create_task", {"status": "todo"}, {"created": notes, "status": "todo"}, None),
        ("brain_update_task", {"task": sub, **started}, {"applied": True, **started}, sub),
        ("brain_update_task", {"task": sub, "status": "blocked"}, {"applied": True}, None),
        ("brain_update_task", {"task": sub}, {"applied": True}, None),
        ("brain_update_task", {"task": sub, **started}, {"applied": False}, None),
        ("brain_create_checkpoint", {"title": "x"}, {"created": "cp-1", "task": sub}, sub),
        ("brain_create_checkpoint", {"title": "x"}, {"created": "cp-1", "task": None}, None),
        # A question about a closed task waits in its follow-up: the result names where it went.
        ("brain_ask_person", {"task": orch}, {"asked": notes}, notes),
        ("brain_submit_review", {"task": notes}, {"submitted": notes, "round": 1}, notes),
    ]


async def test_the_tool_hook_takes_the_task_a_call_names_from_any_result_shape(
    database_url: str, tmp_path: Path
) -> None:
    from app.services.chat_questions import record_tool

    async with app_client(database_url) as client:
        w = await sandbox(client, tmp_path)
    chats = 0
    for tool, arguments, result, expected in named_cases(w):
        for response in shapes(result):
            chats += 1
            with database(database_url) as session:
                call_made = tool_call(tool, {**arguments, "project": "harbor-lights"}, response)
                record_tool(session, "claude", {**call_made, "session_id": f"chat-{chats}"})
            assert worked_on(database_url, f"chat-{chats}") == ([expected] if expected else []), (
                tool,
                arguments,
                response,
            )


async def test_a_failed_call_records_nothing_and_a_text_result_only_what_the_call_names(
    database_url: str, tmp_path: Path
) -> None:
    from app.services.chat_questions import record_tool

    async with app_client(database_url) as client:
        w = await sandbox(client, tmp_path)
    orch = w["orchestrator"]
    failed = {"content": [{"type": "text", "text": json.dumps({"asked": orch})}], "isError": True}
    pack = [{"type": "text", "text": f"PROJECT\nHarbor Lights\n\nCURRENT TASK\n{orch}"}]
    cases = (
        ("brain_ask_person", {"task": orch}, failed, []),  # a failed call changes nothing
        ("brain_context_pack", {"task": orch}, pack, [orch]),  # a pack is text: the call names it
        ("brain_context_pack", {"query": "release"}, pack, []),  # a pack for a search names none
        ("brain_context_pack", {"task": "NOPE-099"}, pack, []),  # no such task
    )
    for number, (tool, arguments, response, expected) in enumerate(cases):
        with database(database_url) as session:
            call_made = tool_call(tool, {**arguments, "project": "harbor-lights"}, response)
            record_tool(session, "claude", {**call_made, "session_id": f"chat-{number}"})
        assert worked_on(database_url, f"chat-{number}") == expected, (tool, arguments)


# ---- cheap when it has nothing to do, and never fails the agent -------------------------------

MOAH_TOOLS = (
    "mcp__project-moah__brain_ask_person",
    "mcp__project-brain__brain_submit_review",
    "mcp__project_moah__brain_create_checkpoint",
    "mcp__project_brain__brain_context_pack",
    "mcp__project-brain__brain_create_task",
    "mcp__project-moah__brain_update_task",
)
OTHER_TOOLS = (
    "Bash",
    "Edit",
    "mcp__filesystem__read_file",
    "mcp__project-moah__brain_search",  # a Moah tool that names no task the session works on
    "mcp__plugin_notes_project-moah__brain_ask_person",  # another server that borrows the name
    "mcp__project-moah-copy__brain_ask_person",
    "project-moah__brain_ask_person",
    None,
    7,
)


@pytest.mark.parametrize("tool", MOAH_TOOLS)
def test_a_moah_tool_call_in_a_valid_chat_is_recorded(tool: str, monkeypatch) -> None:
    from app.services.hook_text import nothing_to_record

    payload = {"session_id": CODEX, "tool_name": tool}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert nothing_to_record(["--agent", "codex", "--hook", "tool"]) is False


@pytest.mark.parametrize("tool", OTHER_TOOLS)
def test_any_other_tool_call_needs_nothing(tool: object, monkeypatch) -> None:
    from app.services.hook_text import nothing_to_record

    payload = {"session_id": SESSION, "tool_name": tool}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert nothing_to_record(["--agent", "claude", "--hook", "tool"]) is True


@pytest.mark.parametrize("session_id", ["bad id with spaces", "", None, 5, "x" * 65])
def test_a_tool_call_without_a_valid_session_id_needs_nothing(session_id, monkeypatch) -> None:
    from app.services.hook_text import nothing_to_record

    payload = {"session_id": session_id, "tool_name": MOAH_TOOLS[0]}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert nothing_to_record(["--agent", "claude", "--hook", "tool"]) is True
    for raw in ("not json", "[]", ""):
        monkeypatch.setattr("sys.stdin", io.StringIO(raw))
        assert nothing_to_record(["--agent", "claude", "--hook", "tool"]) is True


def test_a_tool_call_that_is_not_a_moah_one_ends_before_loading_the_database(
    tmp_path: Path,
) -> None:
    """The hook runs after every tool call the agent makes: most are not Moah's."""
    backend = Path(__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items() if k != "PROJECT_BRAIN_DATABASE_URL"}
    env["PROJECT_BRAIN_DB_PATH"] = str(tmp_path / "moah.db")
    probe = (
        "import sys, runpy\n"
        "sys.argv = ['project-moah-mcp', '--agent', 'claude', '--hook', 'tool']\n"
        "try:\n    runpy.run_module('app.mcp', run_name='__main__')\n"
        "except SystemExit as end:\n    assert end.code == 0, end.code\n"
        "print('sqlalchemy' in sys.modules)"
    )
    for tool, loads in (("Bash", "False"), ("mcp__project-brain__brain_ask_person", "True")):
        payload = json.dumps(
            {"session_id": SESSION, "tool_name": tool, "tool_input": {}, "tool_response": {}}
        )
        done = subprocess.run(
            [sys.executable, "-c", probe],
            input=payload,
            capture_output=True,
            text=True,
            cwd=backend,
            env=env,
            timeout=60,
        )
        assert done.stdout.strip() == loads, done.stderr


BROKEN = [
    {"tool_input": None, "tool_response": None},
    {"tool_input": ["task"], "tool_response": 7},
    {"tool_input": "not json", "tool_response": "not json"},
    {"tool_input": '{"task": ', "tool_response": '{"asked": '},
    {"tool_input": {"task": 5, "project": ["x"]}, "tool_response": {"content": "oops"}},
    {"tool_input": {"task": "x" * 500}, "tool_response": {"structuredContent": []}},
    {"tool_input": {"task": "NOPE-001"}, "tool_response": {"structuredContent": {"result": 3}}},
    {"tool_input": {"task": "NOPE-001"}, "tool_response": [1, None, {"type": "text", "text": 5}]},
    {"tool_input": {"task": "NOPE-001"}, "tool_response": {"content": [{"type": "image"}]}},
    {"tool_input": {"task": "NOPE-001"}, "tool_response": {"asked": "NOPE-001"}},
    {"tool_input": {"task": "../../etc/passwd"}, "tool_response": {"asked": {"x": 1}}},
    {"tool_input": {"task": "NOPE-001"}, "tool_response": "[" * 5000},
    {"tool_input": {"task": "NOPE-001"}, "tool_response": '{"asked":' * 5000},
    {"tool_name": ["mcp__project-brain__brain_ask_person"]},
    {"tool_name": None},
]


async def test_a_broken_tool_hook_input_never_fails_the_agent_or_records_anything(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.models.agent_session import AgentSessionEvent
    from app.models.review import TaskReview

    async with app_client(database_url) as client:
        await sandbox(client, tmp_path)
    for broken in BROKEN:
        run_hook(
            monkeypatch,
            capsys,
            database_url,
            "tool",
            {"tool_name": "mcp__project-brain__brain_ask_person", **broken},
        )
    with database(database_url) as session:
        tasks = session.query(AgentSessionEvent).filter(
            AgentSessionEvent.source.in_(("task", "hook_task"))
        )
        assert tasks.count() == 0
        assert session.query(TaskReview).count() == 0
    # And input that is not even JSON.
    from app.mcp import cli

    monkeypatch.setattr(cli, "get_database_url", lambda: database_url)
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert cli.main(["--agent", "codex", "--hook", "tool"]) == 0
    assert capsys.readouterr().out == ""

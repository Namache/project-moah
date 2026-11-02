"""The session brief's UNFINISHED block: the task the person is in the middle of, what is already
decided for it, and what its last checkpoint left to do.

In the 2026-11-02 test every agent asked the person something a linked decision already
answered, because the brief showed only the latest checkpoint's title and next step."""

import time

import pytest
from httpx import AsyncClient

from app.db.session import make_engine, make_session_factory
from app.models.project import Project
from app.services.brief import HOW_TO, build_brief
from app.services.tokens import base_tokens
from tests.conftest import app_client

pytestmark = pytest.mark.anyio


def brief_for(database_url: str, pid: str) -> tuple[str, str | None]:
    engine = make_engine(database_url)
    try:
        with make_session_factory(engine)() as session:
            project = session.get(Project, pid)
            return build_brief(session, project), project.current_focus_task_id
    finally:
        engine.dispose()


async def make_project(client: AsyncClient, name: str = "Idle Camp") -> str:
    return (await client.post("/api/projects", json={"name": name})).json()["id"]


async def task(client: AsyncClient, pid: str, title: str, **fields: object) -> dict:
    created = await client.post(
        f"/api/projects/{pid}/tasks", json={"title": title, "prefix": "IDLE", **fields}
    )
    assert created.status_code == 201, created.text
    return created.json()


async def memory(client: AsyncClient, pid: str, type_: str, title: str, **fields: object) -> str:
    created = await client.post(
        f"/api/projects/{pid}/memory", json={"type": type_, "title": title, **fields}
    )
    assert created.status_code == 201, created.text
    return created.json()["human_id"]


async def checkpoint(client: AsyncClient, pid: str, title: str, **fields: object) -> None:
    created = await client.post(
        f"/api/projects/{pid}/checkpoints", json={"title": title, "agent": "claude", **fields}
    )
    assert created.status_code == 201, created.text


async def set_status(client: AsyncClient, pid: str, ref: str, status: str) -> None:
    changed = await client.patch(f"/api/projects/{pid}/tasks/{ref}", json={"status": status})
    assert changed.status_code == 200, changed.text


async def test_unfinished_task_lists_what_is_decided_and_left(database_url: str) -> None:
    async with app_client(database_url) as client:
        pid = await make_project(client)
        done = await task(client, pid, "Gems with a migration")
        await set_status(client, pid, done["human_id"], "completed")
        offline = await task(
            client, pid, "Offline progress: gold for time away", status="in_progress"
        )
        ref = offline["human_id"]
        rule = await memory(client, pid, "rule", "Never pay for negative time", importance="high")
        cap = await memory(
            client,
            pid,
            "decision",
            "Offline gains: at most 8 hours, at half rate",
            importance="high",
            task_ids=[offline["id"]],  # linked through the memory's tasks
        )
        no_save = await memory(client, pid, "decision", "A save without lastSeen gets no gold")
        warn = await memory(client, pid, "warning", "Changing the save needs a migration")
        fact = await memory(client, pid, "fact", "Gold per second is 1 at level 1")
        old_bug = await memory(client, pid, "bug", "Gold went negative", is_resolved=True)
        hidden = await memory(
            client,
            pid,
            "decision",
            "Private note",
            ai_visibility="hidden",
            task_ids=[offline["id"]],
        )
        gems = await memory(client, pid, "decision", "Gems are never offline")
        idea = await memory(client, pid, "idea", "Offline chest", task_ids=[offline["id"]])
        guess = await memory(client, pid, "decision", "Guessed link only")
        linked = await memory(client, pid, "decision", "Offline popup shows the gold")
        # Named in the next action and in criteria: an open one counts, a ticked one does not.
        changed = await client.patch(
            f"/api/projects/{pid}/tasks/{ref}", json={"next_action": f"Check {fact} first."}
        )
        assert changed.status_code == 200, changed.text
        for text in (f"Old saves migrate ({warn})", f"Gems stay ({gems})"):
            added = await client.post(
                f"/api/projects/{pid}/tasks/{ref}/criteria", json={"description": text}
            )
            assert added.status_code == 201, added.text
        [ticked] = [c for c in added.json()["acceptance_criteria"] if gems in c["description"]]
        tick = await client.patch(
            f"/api/projects/{pid}/tasks/{ref}/criteria/{ticked['id']}",
            json={"is_completed": True},
        )
        assert tick.status_code == 200, tick.text
        made = await client.post(
            f"/api/projects/{pid}/links",
            json={
                "source": ref,
                "relationship": "relates_to",
                "target": guess,
                "status": "candidate",
            },
        )
        assert made.status_code == 201, made.text
        made = await client.post(
            f"/api/projects/{pid}/links",
            json={"source": linked, "relationship": "applies_to", "target": ref},
        )
        assert made.status_code == 201, made.text
        await checkpoint(
            client,
            pid,
            "Offline gold started",
            task_id=ref,
            remaining_work=f"Half rate and 8-hour cap ({cap});\n  no gold without lastSeen "
            f"({no_save}) or when the clock went back ({rule}); {old_bug} stays fixed.",
            next_steps="Add lastSeen to the save.",
        )

    brief, focus = brief_for(database_url, pid)
    assert focus is None  # reading the brief never sets the focus
    start = brief.index("UNFINISHED:")
    block = brief[start : brief.index("\n\nHOW TO WORK")].splitlines()
    assert block[0] == f"UNFINISHED: {ref} Offline progress: gold for time away (in progress)"
    assert block[1] == "  Already decided for it (follow these; don't ask the person again):"
    # Settled guidance first, by importance, then what is known; the rule is already listed.
    assert block[2:6] == [
        f"  - {cap} Offline gains: at most 8 hours, at half rate",
        f"  - {no_save} A save without lastSeen gets no gold",
        f"  - {linked} Offline popup shows the gold",
        f"  - {warn} Changing the save needs a migration",
    ]
    assert block[6] == f"  - {fact} Gold per second is 1 at level 1"
    assert block[7] == (
        '  Left to do (checkpoint "Offline gold started"): Half rate and 8-hour cap '
        f"({cap}); no gold without lastSeen ({no_save}) or when the clock went back ({rule}); "
        f"{old_bug} stays fixed."
    )
    assert block[8] == (
        f'  Continuing it? Call brain_context_pack(task="{ref}") before you plan or ask: '
        "it has the full records."
    )
    assert len(block) == 9
    for left_out in (hidden, gems, idea, guess, f"- {old_bug}", f"- {rule}"):
        assert left_out not in "\n".join(block[2:7]), left_out
    assert f"- {rule} Never pay for negative time" in brief  # under PROJECT RULES
    # The checkpoint is the shown task's own, so it is not repeated; the focus line is gone.
    assert "LATEST CHECKPOINT" not in brief and "CURRENT FOCUS" not in brief


async def test_several_tasks_in_progress_and_no_checkpoint_shows_none(database_url: str) -> None:
    async with app_client(database_url) as client:
        pid = await make_project(client)
        for title in ("Offline gold", "Shop screen"):
            await task(client, pid, title, status="in_progress")
    brief, _ = brief_for(database_url, pid)
    assert "UNFINISHED" not in brief and "LATEST CHECKPOINT" not in brief


async def test_a_closed_checkpoint_task_falls_back_to_the_one_in_progress(
    database_url: str,
) -> None:
    async with app_client(database_url) as client:
        pid = await make_project(client)
        gems = await task(client, pid, "Gems with a migration", status="in_progress")
        offline = await task(client, pid, "Offline gold", status="in_progress")
        await checkpoint(
            client,
            pid,
            "Gems done",
            task_id=gems["human_id"],
            remaining_work="Nothing.",
            next_steps="Offline progress next.",
        )
        await set_status(client, pid, gems["human_id"], "completed")
    brief, _ = brief_for(database_url, pid)
    assert f"UNFINISHED: {offline['human_id']} Offline gold (in progress)" in brief
    assert "Already decided" not in brief  # nothing is linked to it yet
    assert "Left to do" not in brief  # the checkpoint was for another task
    assert "LATEST CHECKPOINT: Gems done (next: Offline progress next.)" in brief


async def test_the_focus_task_wins_and_long_text_is_cut(database_url: str) -> None:
    async with app_client(database_url) as client:
        pid = await make_project(client)
        other = await task(client, pid, "Shop screen", status="in_progress")
        focus = await task(client, pid, "Offline gold")
        started = await client.post(f"/api/projects/{pid}/tasks/{focus['human_id']}/start")
        assert started.status_code == 200, started.text
        pinned = await memory(
            client, pid, "decision", "Gold is an integer", is_pinned=True, task_ids=[focus["id"]]
        )
        long_title = "Offline gold " + " ".join(["very"] * 30) + " long"
        wordy = await memory(client, pid, "warning", long_title, task_ids=[focus["id"]])
        await checkpoint(
            client,
            pid,
            "Offline started",
            task_id=focus["human_id"],
            remaining_work=" ".join(["step"] * 100),
        )
        await checkpoint(client, pid, "Shop started", task_id=other["human_id"])

    brief, focus_id = brief_for(database_url, pid)
    assert focus_id == focus["id"]
    assert f"UNFINISHED: {focus['human_id']} Offline gold (in progress)" in brief
    # Pinned, so it is under KEY DECISIONS already and not repeated.
    assert f"KEY DECISIONS AND WARNINGS\n- {pinned} Gold is an integer" in brief
    assert f"  - {pinned}" not in brief
    [title_line] = [line for line in brief.splitlines() if line.startswith(f"  - {wordy}")]
    assert title_line.endswith("...") and len(title_line) <= len(f"  - {wordy} ") + 90
    [left] = [line for line in brief.splitlines() if line.startswith("  Left to do")]
    text = left.split(": ", 1)[1]
    assert text.endswith("step...") and len(text) <= 300
    # The latest checkpoint is another task's, so it keeps its own line.
    assert "LATEST CHECKPOINT: Shop started" in brief


async def test_the_brief_stays_cheap(database_url: str) -> None:
    async with app_client(database_url) as client:
        pid = await make_project(client)
        work = await task(client, pid, "Offline gold", status="in_progress")
        for n in range(40):
            await memory(client, pid, "decision", f"Choice {n}", task_ids=[work["id"]])
        await checkpoint(client, pid, "Started", task_id=work["human_id"], remaining_work="x")
    brief_for(database_url, pid)  # warm up
    began = time.perf_counter()
    brief, _ = brief_for(database_url, pid)
    assert time.perf_counter() - began < 2.0
    assert brief.count("\n  - DEC-") == 6  # capped


def test_how_to_says_to_look_before_asking_and_to_write_back() -> None:
    assert "earlier answers" in HOW_TO and "before you ask the person" in HOW_TO
    assert "needs no permission" in HOW_TO and "brain_create_checkpoint" in HOW_TO
    assert "follow-ups on the same work" not in HOW_TO
    assert "this session's task" not in HOW_TO  # mechanics agents do not need up front
    assert base_tokens(HOW_TO) <= 287  # the October-to-November HOW_TO cost


def test_server_instructions_stay_short_and_defer_to_the_brief() -> None:
    from app.mcp.server import INSTRUCTIONS

    # Read in every session next to the brief (362 tokens before November 2026).
    assert base_tokens(INSTRUCTIONS) <= 180
    assert "follow-ups on the same work" not in INSTRUCTIONS
    assert "brain_brief" in INSTRUCTIONS and "before you ask" in INSTRUCTIONS
    assert "needs no" in INSTRUCTIONS and "permission" in INSTRUCTIONS

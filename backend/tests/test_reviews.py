"""The Review screen's backend: agents hand finished tasks over, the person accepts or sends them
back, and a sent-back task reaches the next agent through its brief, its task and a prompt.

The world is a small but lived-in project: rules, a decision, a task with acceptance criteria that
an agent worked on and checkpointed, and an older suggestion still waiting."""

from pathlib import Path

import pytest
from httpx import AsyncClient

from tests.conftest import app_client
from tests.test_images import png
from tests.test_mcp import agent, call

pytestmark = pytest.mark.anyio


async def world(client: AsyncClient, tmp_path: Path) -> dict:
    root = tmp_path / "trailhead"
    (root / "src").mkdir(parents=True)
    pid = (
        await client.post("/api/projects", json={"name": "Trailhead", "root_path": str(root)})
    ).json()["id"]
    for title in ("Ask before adding a dependency", "Every screen works in dark mode"):
        await client.post(
            f"/api/projects/{pid}/memory", json={"type": "rule", "title": title, "content": title}
        )
    await client.post(
        f"/api/projects/{pid}/memory",
        json={"type": "decision", "title": "Camps hold 6 people", "content": "Capacity is 6."},
    )
    task = (
        await client.post(
            f"/api/projects/{pid}/tasks",
            json={
                "title": "Camp capacity badge",
                "prefix": "CAMP",
                "acceptance_criteria": ["Badge shows free places", "Works in dark mode"],
            },
        )
    ).json()
    await client.post(f"/api/projects/{pid}/tasks/{task['id']}/start")
    other = (
        await client.post(f"/api/projects/{pid}/tasks", json={"title": "Trail map legend"})
    ).json()
    return {"pid": pid, "root": root, "task": task["human_id"], "other": other["human_id"]}


SUBMIT = {
    "summary": "The camp card now shows how many places are free, in both themes.",
    "done": ["Badge on every camp card", "Dark mode colours"],
    "not_done": ["No test for a full camp yet"],
    "how_to_check": "1. Open Camps\n2. Look at any card",
    "details": "| Camp | Free |\n|---|---|\n| North | 2 |\n\n> [!WARNING]\n> Full camps show 0.",
}


def submit_review(database_url: str, pid: str, task: str, agent_name: str = "claude", **extra):
    """Submit as an agent would, in-process, with two screenshots."""
    from app.db.session import make_engine, make_session_factory
    from app.schemas.review import ReviewSubmit
    from app.services.activity import acting_as
    from app.services.reviews import ReviewService, Screenshot

    engine = make_engine(database_url)
    try:
        with make_session_factory(engine)() as session, acting_as(agent_name, agent_name):
            shots = [
                Screenshot(png(4, 3), "light.png", "Light theme"),
                Screenshot(png(4, 3), "dark.png", None),
            ]
            review = ReviewService(session).submit(
                pid, task, ReviewSubmit(**{**SUBMIT, **extra}), agent_name, shots
            )
            return review.round
    finally:
        engine.dispose()


def brief(database_url: str, pid: str) -> str:
    from app.db.session import make_engine, make_session_factory
    from app.models.project import Project
    from app.services.brief import build_brief

    engine = make_engine(database_url)
    try:
        with make_session_factory(engine)() as session:
            return build_brief(session, session.get(Project, pid))
    finally:
        engine.dispose()


async def test_a_review_round_trip_accept_after_a_send_back(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
    pid, task = w["pid"], w["task"]
    assert submit_review(database_url, pid, task) == 1

    async with app_client(database_url) as client:
        assert (await client.get(f"/api/projects/{pid}/tasks/{task}")).json()["status"] == "review"
        timeline = (await client.get("/api/reviews")).json()
        [item] = timeline["waiting"]
        assert (item["kind"], item["ref"], item["agent"], item["screenshots"]) == (
            "task",
            task,
            "claude",
            2,
        )
        assert item["summary"].startswith("The camp card") and item["verdict"] is None
        pending = (await client.get("/api/reviews/pending")).json()
        assert pending["total"] == 1 and pending["by_project"] == {pid: 1}
        assert pending["newest"][0]["key"] == item["key"]

        detail = (await client.get(f"/api/projects/{pid}/tasks/{task}/review")).json()
        current = detail["current"]
        assert current["done"] == SUBMIT["done"] and current["not_done"] == SUBMIT["not_done"]
        assert [s["caption"] for s in current["screenshots"]] == ["Light theme", None]
        assert [c["description"] for c in detail["criteria"]] == [
            "Badge shows free places",
            "Works in dark mode",
        ]
        shot = await client.get(
            f"/api/projects/{pid}/review-files/{current['screenshots'][0]['id']}"
        )
        assert shot.status_code == 200 and shot.headers["content-type"] == "image/png"

        # Sending back needs words (or a file), so the agent knows what to fix.
        url = f"/api/projects/{pid}/tasks/{task}/review"
        refused = await client.post(url + "/decision", json={"verdict": "reject"})
        assert refused.status_code == 422
        note = await client.post(
            url + "/files?filename=steps.txt", content=b"Open North camp\nBadge says -1"
        )
        assert note.status_code == 201 and note.json()["media_type"] == "text/plain"
        picture = await client.post(url + "/files?filename=bug.png", content=png())
        assert picture.status_code == 201
        binary = await client.post(url + "/files?filename=a.bin", content=b"\x00\x01\x02")
        assert binary.status_code == 422
        gone = await client.delete(f"/api/projects/{pid}/review-files/{picture.json()['id']}")
        assert gone.status_code == 204
        await client.post(url + "/files?filename=bug.png", content=png())
        sent = await client.post(
            url + "/decision",
            json={"verdict": "reject", "comment": "A full camp shows -1. It should say Full."},
        )
        assert sent.status_code == 200
        body = sent.json()
        assert body["task_status"] == "in_progress" and body["current"]["status"] == "rejected"
        assert len(body["current"]["feedback"]) == 2
        # A sent comment's files are part of the record now.
        kept = await client.delete(
            f"/api/projects/{pid}/review-files/{body['current']['feedback'][0]['id']}"
        )
        assert kept.status_code == 409
        reviewed = (await client.get("/api/reviews")).json()
        assert reviewed["waiting"] == []
        assert reviewed["reviewed"][0]["verdict"] == "rejected"

        prompt = (await client.get(url + "/fix-prompt?agent=codex")).json()
        assert "A full camp shows -1" in prompt["prompt"] and prompt["url"].startswith("codex://")
        assert "brain_submit_review" in prompt["prompt"] and "2 file(s)" in prompt["prompt"]

    text = brief(database_url, pid)
    assert "SENT BACK FROM REVIEW" in text and "A full camp shows -1" in text
    assert "(+2 attached file(s))" in text

    async with agent(database_url, "codex") as session:
        error, detail = await call(session, "brain_get_task", project="trailhead", task=task)
        assert not error and detail["review"]["status"].startswith("sent back")
        assert detail["review"]["comment"].startswith("A full camp")
        texts = [a for a in detail["review"]["attachments"] if "text" in a]
        assert texts[0]["text"].startswith("Open North camp")
        result = await session.call_tool(
            "brain_view_images", {"project": "trailhead", "record": task}
        )
        assert sum(1 for block in result.content if block.type == "image") == 1

    assert submit_review(database_url, pid, task, "codex", not_done=[]) == 2
    assert "SENT BACK" not in brief(database_url, pid)

    async with app_client(database_url) as client:
        detail = (await client.get(f"/api/projects/{pid}/tasks/{task}/review")).json()
        assert detail["current"]["round"] == 2 and detail["current"]["agent"] == "codex"
        assert [r["status"] for r in detail["earlier"]] == ["rejected"]
        accepted = await client.post(
            f"/api/projects/{pid}/tasks/{task}/review/decision",
            json={"verdict": "accept", "comment": "Lovely."},
        )
        # Accepting moves the task to Done; it leaves the board only when archived.
        assert accepted.status_code == 200 and accepted.json()["task_status"] == "completed"
        done = (await client.get(f"/api/projects/{pid}/tasks/{task}")).json()
        assert done["completed_at"] and not done["archived_at"]
        # Reviewed lists tasks, not rounds: one line, with the latest decision.
        reviewed = (await client.get("/api/reviews")).json()["reviewed"]
        assert [(r["ref"], r["verdict"]) for r in reviewed] == [(task, "accepted")]
        again = await client.post(
            f"/api/projects/{pid}/tasks/{task}/review/decision", json={"verdict": "accept"}
        )
        assert again.status_code == 409


async def test_a_task_moved_to_review_without_a_review_shows_its_checkpoint(
    database_url: str, tmp_path: Path
) -> None:
    """Agents can't move a task to review without a report, but a person can drag it there on
    the board, and tasks moved before the rule have none either: they show the checkpoint."""
    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
    pid, task = w["pid"], w["task"]
    async with agent(database_url) as session:
        error, _ = await call(
            session,
            "brain_create_checkpoint",
            project="trailhead",
            task=task,
            title="Badge done",
            summary="Badge added to camp cards.",
            completed_work="- Badge component\n- Wired to capacity",
            remaining_work="1. Tests for full camps",
            problems="Colours are off in dark mode",
        )
        assert not error

    async with app_client(database_url) as client:
        moved = await client.post(
            f"/api/projects/{pid}/tasks/{task}/move", json={"status": "review", "index": 0}
        )
        assert moved.status_code == 200, moved.text
        [item] = (await client.get("/api/reviews")).json()["waiting"]
        assert item["generated"] is True and item["agent"] == "claude"
        assert item["summary"] == "Badge added to camp cards."
        detail = (await client.get(f"/api/projects/{pid}/tasks/{task}/review")).json()
        current = detail["current"]
        assert current["id"] is None and current["generated"] is True
        assert current["done"] == ["Badge component", "Wired to capacity"]
        assert current["not_done"] == ["Tests for full camps", "Colours are off in dark mode"]
        decided = await client.post(
            f"/api/projects/{pid}/tasks/{task}/review/decision", json={"verdict": "accept"}
        )
        assert decided.status_code == 200 and decided.json()["current"]["id"]


async def test_a_batch_checkpoint_shows_only_the_lines_about_this_task(
    database_url: str, tmp_path: Path
) -> None:
    """Agents often write one note for a batch of tasks, filed under one of them. The review of
    each task picks out its own lines and leaves the rest of the note folded underneath."""
    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
        pid, task = w["pid"], w["task"]
        sign = (
            await client.post(
                f"/api/projects/{pid}/tasks", json={"title": "Camp sign colours", "prefix": "CAMP"}
            )
        ).json()["human_id"]
    async with agent(database_url) as session:
        for args in (
            dict(
                task=task,
                title="Badge sketched",
                summary="Badge layout agreed with the capacity decision.",
                completed_work="Badge component with free places",
                next_steps="Wire it to the camp list",
            ),
            dict(
                task=sign,
                title="Camp batch pushed",
                summary=f"Pushed 2 commits ({task} capacity badge wiring, {sign} sign colours).",
                completed_work=(
                    f"{sign}: sign colours follow the theme. Contrast checked in both themes.\n"
                    f"{task}: badge wired to the camp list. Full camps show 0."
                ),
                remaining_work=f"{sign} needs a dark-mode icon. Waiting for the icon set.",
                next_steps=f"{task}: add a test for a full camp.",
            ),
        ):
            error, _ = await call(session, "brain_create_checkpoint", project="trailhead", **args)
            assert not error

    async with app_client(database_url) as client:
        # Moved to Review on the board, as tasks without a report get there now.
        await client.post(
            f"/api/projects/{pid}/tasks/{task}/move", json={"status": "review", "index": 0}
        )
        url = f"/api/projects/{pid}/tasks/{task}/review"
        current = (await client.get(url)).json()["current"]
        assert current["generated"] is True and current["left_out"] is True
        assert current["done"] == [
            "Badge component with free places",
            "Badge wired to the camp list. Full camps show 0.",
        ]
        # The sign's leftover is not this task's.
        assert current["not_done"] == []
        assert current["next_steps"] == ["Add a test for a full camp."]
        # The summary of the newest note about this task alone (the batch note's is not).
        assert current["summary"] == "Badge layout agreed with the capacity decision."
        assert [n["title"] for n in current["notes"]] == ["Camp batch pushed", "Badge sketched"]
        assert [n["filed_here"] for n in current["notes"]] == [False, True]
        assert current["details"] is None

        # Accepted, it still reads the same from Reviewed.
        await client.post(f"{url}/decision", json={"verdict": "accept"})
        current = (await client.get(url)).json()["current"]
        assert current["status"] == "accepted" and current["id"]
        assert current["done"][1] == "Badge wired to the camp list. Full camps show 0."
        assert current["next_steps"] == ["Add a test for a full camp."]


async def test_finished_work_reaches_review_even_without_the_agents_report(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
    pid, task, other = w["pid"], w["task"], w["other"]
    async with agent(database_url) as session:
        await call(
            session,
            "brain_create_checkpoint",
            project="trailhead",
            task=task,
            title="Camp badge built",
            completed_work="- Badge on every camp card\n- Dark mode colours",
            remaining_work="- No test for a full camp yet",
        )
        error, out = await call(
            session, "brain_update_task", project="trailhead", task=task, status="completed"
        )
        # Moved, with a report Moah drafts, and the agent is asked for a better one.
        assert not error and out["applied"] is True and out["status"] == "review"
        assert "Moah drafted" in out["next"] and f'brain_submit_review(task="{task}"' in out["next"]
        # The old "complete this task" suggestion moves the task to review too.
        error, out = await call(
            session,
            "brain_create_proposal",
            project="trailhead",
            proposal_type="complete_task",
            target=other,
            reason="Done",
        )
        assert not error and out["status"] == "review" and "Moah drafted" in out["message"]

    async with app_client(database_url) as client:
        waiting = (await client.get("/api/reviews")).json()["waiting"]
        assert sorted(item["ref"] for item in waiting) == sorted([task, other])
        current = (await client.get(f"/api/projects/{pid}/tasks/{task}/review")).json()["current"]
        assert current["generated"] and "Badge on every camp card" in current["done"]

    # Once the agent's own report waits, it is no longer asked for one.
    submit_review(database_url, pid, task)
    async with agent(database_url) as session:
        error, out = await call(
            session, "brain_update_task", project="trailhead", task=task, status="completed"
        )
        assert not error and out["status"] == "review" and "next" not in out


async def test_suggestions_share_the_timeline_and_a_send_back_settles_them(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
        pid, task = w["pid"], w["task"]
        suggestion = await client.post(
            f"/api/projects/{pid}/proposals",
            json={
                "proposal_type": "create_memory",
                "payload": {"type": "warning", "title": "Snow closes the north trail"},
                "reason": "Seen in the trail data",
            },
        )
        assert suggestion.status_code == 201
        # An older agent asked to complete the task the usual way of the time.
        old = await client.post(
            f"/api/projects/{pid}/proposals",
            json={"proposal_type": "complete_task", "target": task, "reason": "Done"},
        )
        assert old.status_code == 201
        kinds = [i["kind"] for i in (await client.get("/api/reviews")).json()["waiting"]]
        assert sorted(kinds) == ["suggestion", "suggestion"]

    submit_review(database_url, pid, task)
    async with app_client(database_url) as client:
        waiting = (await client.get("/api/reviews")).json()["waiting"]
        # The task's own review stands in for its completion suggestion.
        assert sorted((i["kind"], i["ref"]) for i in waiting) == [
            ("suggestion", "PROP-001"),
            ("task", task),
        ]
        only = (await client.get(f"/api/reviews?project_id={pid}")).json()
        assert len(only["waiting"]) == 2
        await client.post(
            f"/api/projects/{pid}/tasks/{task}/review/decision",
            json={"verdict": "reject", "comment": "Not yet"},
        )
        proposal = (await client.get(f"/api/projects/{pid}/proposals/PROP-002")).json()
        assert proposal["status"] == "rejected" and "Not yet" in proposal["review_note"]
        reviewed = (await client.get("/api/reviews")).json()["reviewed"]
        assert {(r["kind"], r["verdict"]) for r in reviewed} == {
            ("task", "rejected"),
            ("suggestion", "rejected"),
        }


async def test_agents_submit_screenshots_by_path(database_url: str, tmp_path: Path) -> None:
    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
    shot = tmp_path / "camp card.png"
    shot.write_bytes(png(8, 6))
    notes = tmp_path / "notes.txt"
    notes.write_text("not a picture")
    async with agent(database_url) as session:
        tools = {t.name: t for t in (await session.list_tools()).tools}
        assert "screenshot" in tools["brain_submit_review"].description
        error, text = await call(
            session,
            "brain_submit_review",
            project="trailhead",
            task=w["task"],
            summary="Badge added.",
            done=["Badge"],
            screenshots=[str(tmp_path / "missing.png")],
        )
        assert error and "No screenshot file" in text
        error, text = await call(
            session,
            "brain_submit_review",
            project="trailhead",
            task=w["task"],
            summary="Badge added.",
            done=["Badge"],
            screenshots=[str(notes)],
        )
        assert error and "PNG, JPEG, WebP or GIF" in text
        error, out = await call(
            session,
            "brain_submit_review",
            project="trailhead",
            task=w["task"],
            summary="Badge added.",
            done=["Badge"],
            screenshots=[str(shot)],
            captions=["The North camp card"],
        )
        assert not error and out["submitted"] == w["task"] and out["screenshots"] == 1
        assert out["status"] == "review" and "note" not in out
        error, out = await call(
            session,
            "brain_submit_review",
            project="trailhead",
            task=w["other"],
            summary="Legend drawn.",
            done=["Legend"],
        )
        assert not error and "No screenshots" in out["note"]
        error, detail = await call(session, "brain_get_task", project="trailhead", task=w["task"])
        assert detail["review"]["status"] == "waiting for the person's review"
        assert shot.exists()  # files outside Moah's own folder are never touched

    async with app_client(database_url) as client:
        detail = (await client.get(f"/api/projects/{w['pid']}/tasks/{w['task']}/review")).json()
        [picture] = detail["current"]["screenshots"]
        assert (picture["filename"], picture["width"], picture["caption"]) == (
            "camp card.png",
            8,
            "The North camp card",
        )
        assert picture["created_by"] == "claude"


async def test_moving_a_task_on_the_board_settles_its_waiting_review(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
        pid, task = w["pid"], w["task"]
        assert submit_review(database_url, pid, task) == 1
        # Dragged from Review to Done on the board: that accepts the work.
        moved = await client.post(
            f"/api/projects/{pid}/tasks/{task}/move", json={"status": "completed", "index": 0}
        )
        assert moved.status_code == 200, moved.text
        timeline = (await client.get("/api/reviews")).json()
        assert not [i for i in timeline["waiting"] if i["kind"] == "task"]
        [row] = [i for i in timeline["reviewed"] if i["ref"] == task]
        assert row["verdict"] == "accepted" and row["moved_to"] == "completed"
        assert row["task_status"] == "completed"

        # Reopened, handed over again and dragged back to In progress: sent back without a
        # comment, which the brief leaves out because there is nothing for the agent to read.
        await client.patch(f"/api/projects/{pid}/tasks/{task}", json={"status": "in_progress"})
        assert submit_review(database_url, pid, task) == 2
        waiting = (await client.get("/api/reviews")).json()["waiting"]
        assert [i["task_status"] for i in waiting if i["ref"] == task] == ["review"]
        await client.patch(f"/api/projects/{pid}/tasks/{task}", json={"status": "in_progress"})
        timeline = (await client.get("/api/reviews")).json()
        latest = [i for i in timeline["reviewed"] if i["ref"] == task][0]
        assert latest["verdict"] == "rejected" and latest["moved_to"] == "in_progress"
        assert latest["round"] == 2 and latest["task_status"] == "in_progress"
        detail = (await client.get(f"/api/projects/{pid}/tasks/{task}/review")).json()
        assert detail["current"]["moved_to"] == "in_progress"
    assert "SENT BACK" not in brief(database_url, pid)


async def test_an_agent_taking_a_task_back_withdraws_its_review(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
    pid, task = w["pid"], w["task"]
    submit_review(database_url, pid, task)
    async with agent(database_url, "codex") as session:
        error, out = await call(
            session, "brain_update_task", task=task, status="in_progress", project=pid
        )
    assert not error, out
    async with app_client(database_url) as client:
        timeline = (await client.get("/api/reviews")).json()
    assert not [i for i in timeline["waiting"] + timeline["reviewed"] if i["ref"] == task]


async def test_an_agent_asks_the_person_and_the_answer_reaches_the_next_agent(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
    pid, task = w["pid"], w["task"]
    submit_review(database_url, w["pid"], w["other"])  # other work already waits in Review
    async with agent(database_url) as session:
        error, out = await call(
            session,
            "brain_ask_person",
            task=task,
            question="Should a full camp show 0 or a red Full label?",
            context="DEC-001 sets capacity, not how a full camp looks.",
            options=["Show 0", "Red Full label"],
            project=pid,
        )
    assert not error, out
    assert out["status"] == "blocked" and "Stop" in out["message"]
    assert "1 question(s)" in brief(database_url, pid)

    async with app_client(database_url) as client:
        timeline = (await client.get("/api/reviews")).json()
        # The question comes first: work is stuck until it is answered.
        first, second = timeline["waiting"][:2]
        assert (first["ref"], first["question"], first["task_status"]) == (task, True, "blocked")
        assert second["ref"] == w["other"] and not second["question"]
        pending = (await client.get("/api/reviews/pending")).json()
        assert pending["total"] == 2 and pending["newest"][0]["question"] is True
        url = f"/api/projects/{pid}/tasks/{task}/review"
        detail = (await client.get(url)).json()
        assert detail["current"]["kind"] == "question"
        assert detail["current"]["options"] == ["Show 0", "Red Full label"]
        assert (await client.post(url + "/decision", json={"verdict": "accept"})).status_code == 409
        empty = await client.post(url + "/decision", json={"verdict": "answer"})
        assert empty.status_code == 422
        answered = await client.post(
            url + "/decision",
            json={"verdict": "answer", "comment": "Red Full label, like DEC-001."},
        )
        assert answered.status_code == 200, answered.text
        body = answered.json()
        assert body["task_status"] == "in_progress" and body["current"]["status"] == "answered"
        timeline = (await client.get("/api/reviews")).json()
        assert [i["ref"] for i in timeline["waiting"]] == [w["other"]]
        [row] = [i for i in timeline["reviewed"] if i["ref"] == task]
        assert row["verdict"] == "answered" and row["question"]
        prompt = (await client.get(url + "/fix-prompt?agent=claude")).json()["prompt"]
        assert "My answer\nRed Full label" in prompt and "You asked" in prompt

    text = brief(database_url, pid)
    assert "ANSWERED IN REVIEW" in text and "Red Full label" in text
    assert "question(s)" not in text
    async with agent(database_url, "codex") as session:
        error, detail = await call(session, "brain_get_task", project=pid, task=task)
    assert not error and detail["review"]["status"].startswith("answered by the person")
    assert detail["review"]["question"].startswith("Should a full camp")
    # Until an agent hands the task over again, the answer stays in the brief.
    submit_review(database_url, pid, task)
    assert "ANSWERED IN REVIEW" not in brief(database_url, pid)


async def test_accepted_work_can_be_reopened_with_a_comment(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
    pid, task = w["pid"], w["task"]
    submit_review(database_url, pid, task)
    async with app_client(database_url) as client:
        url = f"/api/projects/{pid}/tasks/{task}/review"
        early = await client.post(url + "/reopen", json={"comment": "Not yet"})
        assert early.status_code == 409  # nothing accepted to take back yet
        accepted = await client.post(url + "/decision", json={"verdict": "accept"})
        assert accepted.json()["task_status"] == "completed"
        # Accepting made no tasks from the "Not done" line by itself.
        tasks = (await client.get(f"/api/projects/{pid}/tasks")).json()
        assert not [t for t in tasks if t["title"] == SUBMIT["not_done"][0]]

        assert (await client.post(url + "/reopen", json={"comment": "  "})).status_code == 422
        reopened = await client.post(
            url + "/reopen", json={"comment": "The badge is wrong on a full camp after all."}
        )
        assert reopened.status_code == 200
        body = reopened.json()
        assert body["task_status"] == "in_progress"
        assert body["current"]["status"] == "rejected"
        assert body["current"]["comment"].startswith("The badge is wrong")
        task_now = (await client.get(f"/api/projects/{pid}/tasks/{task}")).json()
        assert task_now["status"] == "in_progress" and not task_now["completed_at"]
        timeline = (await client.get("/api/reviews")).json()
        assert timeline["waiting"] == []
        assert [(r["ref"], r["verdict"]) for r in timeline["reviewed"]] == [(task, "rejected")]
        # Once is enough: it is not accepted any more.
        again = await client.post(url + "/reopen", json={"comment": "Again"})
        assert again.status_code == 409
        prompt = (await client.get(url + "/fix-prompt?agent=claude")).json()
        assert "The badge is wrong on a full camp" in prompt["prompt"]
        events = (await client.get(f"/api/projects/{pid}/activity")).json()
        assert any(e["event_type"] == "REVIEW_REOPENED" for e in events)

    # The next agent reads the comment first, like any send-back.
    text = brief(database_url, pid)
    assert "SENT BACK FROM REVIEW" in text and "The badge is wrong" in text


async def test_an_accept_can_be_undone_for_a_few_minutes(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import timedelta

    from app.services import reviews

    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
    pid, task = w["pid"], w["task"]
    submit_review(database_url, pid, task)
    async with app_client(database_url) as client:
        url = f"/api/projects/{pid}/tasks/{task}/review"
        assert (await client.post(url + "/undo")).status_code == 409  # nothing accepted yet
        await client.post(url + "/decision", json={"verdict": "accept", "comment": "Nice"})
        undone = await client.post(url + "/undo")
        assert undone.status_code == 200
        body = undone.json()
        # As if Accept was never pressed: the same report waits again, with no decision on it.
        assert body["task_status"] == "review"
        assert body["current"]["status"] == "pending" and body["current"]["round"] == 1
        assert body["current"]["comment"] is None and body["earlier"] == []
        timeline = (await client.get("/api/reviews")).json()
        assert [r["ref"] for r in timeline["waiting"]] == [task] and timeline["reviewed"] == []
        events = (await client.get(f"/api/projects/{pid}/activity")).json()
        assert any(e["event_type"] == "REVIEW_UNDONE" for e in events)
        assert (await client.post(url + "/undo")).status_code == 409  # once
        # Later than the window, Undo is refused: Reopen (with a comment) is the way then.
        await client.post(url + "/decision", json={"verdict": "accept"})
        monkeypatch.setattr(reviews, "UNDO_WINDOW", timedelta(seconds=-1))
        late = await client.post(url + "/undo")
        assert late.status_code == 409 and "Reopen" in late.json()["detail"]


async def test_work_accepted_on_the_board_can_be_reopened_too(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
    pid, task = w["pid"], w["task"]
    submit_review(database_url, pid, task)
    async with app_client(database_url) as client:
        await client.post(
            f"/api/projects/{pid}/tasks/{task}/move", json={"status": "completed", "index": 0}
        )
        [item] = (await client.get("/api/reviews")).json()["reviewed"]
        assert (item["verdict"], item["moved_to"]) == ("accepted", "completed")
        reopened = await client.post(
            f"/api/projects/{pid}/tasks/{task}/review/reopen",
            json={"comment": "Dragged to Done too early."},
        )
        assert reopened.json()["current"]["moved_to"] is None
        assert reopened.json()["task_status"] == "in_progress"


async def test_a_task_that_is_only_blocked_does_not_wait_in_review(
    database_url: str, tmp_path: Path
) -> None:
    """Blocked on a supplier or a date is not a question for the person. Only a question an
    agent asked waits in Review."""
    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
    pid, task = w["pid"], w["task"]
    async with agent(database_url) as session:
        await call(
            session,
            "brain_create_checkpoint",
            project=pid,
            task=task,
            title="Waiting on the camp owners",
            summary="Badge works; the owners still have to send their capacity list.",
            problems="Capacity list not sent yet",
        )
        error, out = await call(
            session, "brain_update_task", task=task, status="blocked", project=pid
        )
    assert not error and "brain_ask_person" in out["next"]
    async with app_client(database_url) as client:
        timeline = (await client.get("/api/reviews")).json()
        assert timeline["waiting"] == [] and timeline["reviewed"] == []
        assert (await client.get("/api/reviews/pending")).json()["total"] == 0
        missing = await client.get(f"/api/projects/{pid}/tasks/{task}/review")
        assert missing.status_code == 404
    async with agent(database_url) as session:
        await call(session, "brain_ask_person", task=task, question="Green or grey?", project=pid)
    async with app_client(database_url) as client:
        [item] = (await client.get("/api/reviews")).json()["waiting"]
        assert (item["ref"], item["question"], item["generated"]) == (task, True, False)


async def test_an_agents_question_settles_on_the_board_or_when_it_moves_on(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
    pid, task = w["pid"], w["task"]
    async with agent(database_url) as session:
        await call(
            session,
            "brain_ask_person",
            task=task,
            question="Which colour for a full camp?",
            project=pid,
        )
    async with app_client(database_url) as client:
        # The person blocks another task themselves: that one does not wait for them.
        await client.patch(f"/api/projects/{pid}/tasks/{w['other']}", json={"status": "blocked"})
        timeline = (await client.get("/api/reviews")).json()
        [item] = timeline["waiting"]
        assert (item["ref"], item["question"], item["generated"]) == (task, True, False)
        detail = (await client.get(f"/api/projects/{pid}/tasks/{task}/review")).json()
        assert detail["current"]["kind"] == "question"
        assert detail["current"]["summary"] == "Which colour for a full camp?"
        # Dragged to To do on the board: the question counts as answered there.
        await client.post(
            f"/api/projects/{pid}/tasks/{task}/move", json={"status": "todo", "index": 0}
        )
        assert (await client.get("/api/reviews")).json()["waiting"] == []

    # An agent that got its answer in the chat and moves on withdraws its question.
    async with agent(database_url) as session:
        await call(session, "brain_update_task", task=task, status="in_progress", project=pid)
        await call(session, "brain_ask_person", task=task, question="Green or grey?", project=pid)
        await call(session, "brain_update_task", task=task, status="in_progress", project=pid)
    async with app_client(database_url) as client:
        timeline = (await client.get("/api/reviews")).json()
    # Only the board answer from before is listed; the withdrawn question is not.
    assert [i["verdict"] for i in timeline["reviewed"] if i["ref"] == task] == ["answered"]
    assert not [i for i in timeline["waiting"] if i["ref"] == task]
    assert "ANSWERED IN REVIEW" not in brief(database_url, pid)


async def test_accept_ticks_criteria_and_turns_leftovers_into_tasks(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
    pid, task = w["pid"], w["task"]
    submit_review(
        database_url, pid, task, not_done=["No test for a full camp yet", "Gamepad focus order"]
    )
    async with app_client(database_url) as client:
        url = f"/api/projects/{pid}/tasks/{task}/review"
        detail = (await client.get(url)).json()
        badge, dark = detail["criteria"]
        # One line made into a task straight from the report.
        made = await client.post(url + "/follow-ups", json={"items": ["Gamepad focus order"]})
        assert made.status_code == 200, made.text
        [first] = made.json()["current"]["follow_ups"]
        assert (first["text"], first["task_status"]) == ("Gamepad focus order", "todo")
        # Accept: the badge criterion is met, dark mode is not; what is left goes to Backlog.
        accepted = await client.post(
            url + "/decision",
            json={
                "verdict": "accept",
                "criteria": [{"id": badge["id"], "met": True}, {"id": dark["id"], "met": False}],
                "follow_ups": [
                    "No test for a full camp yet",
                    "Gamepad focus order",
                    dark["description"],
                ],
                "follow_up_status": "backlog",
            },
        )
        assert accepted.status_code == 200, accepted.text
        body = accepted.json()
        assert body["task_status"] == "completed"
        assert [c["is_completed"] for c in body["criteria"]] == [True, False]
        follow_ups = body["current"]["follow_ups"]
        assert [f["text"] for f in follow_ups] == [
            "Gamepad focus order",
            "No test for a full camp yet",
            "Works in dark mode",
        ]
        assert [f["task_status"] for f in follow_ups] == ["todo", "backlog", "backlog"]
        new = (await client.get(f"/api/projects/{pid}/tasks/{follow_ups[1]['task_ref']}")).json()
        assert new["description"].startswith(f"Left over from {task}")
        assert [r["task"]["human_id"] for r in new["relationships"]] == [task]


async def test_rejecting_records_only_the_criteria_marked_unmet(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
        pid, task = w["pid"], w["task"]
        criteria = (await client.get(f"/api/projects/{pid}/tasks/{task}")).json()[
            "acceptance_criteria"
        ]
        badge, dark = criteria
        await client.patch(
            f"/api/projects/{pid}/tasks/{task}/criteria/{dark['id']}", json={"is_completed": True}
        )
        submit_review(database_url, pid, task)
        url = f"/api/projects/{pid}/tasks/{task}/review"
        sent = await client.post(
            url + "/decision",
            json={
                "verdict": "reject",
                "comment": "Dark mode badge is unreadable.",
                "criteria": [{"id": badge["id"], "met": True}, {"id": dark["id"], "met": False}],
            },
        )
        assert sent.status_code == 200, sent.text
        # Leaving the badge ticked on a rejection is not a check; unticking dark mode is.
        assert [c["is_completed"] for c in sent.json()["criteria"]] == [False, False]
        prompt = (await client.get(url + "/fix-prompt?agent=claude")).json()["prompt"]
        assert "Acceptance criteria not met yet\n- Badge shows free places" in prompt

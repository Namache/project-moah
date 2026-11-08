"""Work that waits for the person reaches Review by itself: an agent's checkpoint that says it
waits (for an OK, a pick, a review) opens one question for its task, its later notes keep that
question current, and a note that moves on settles it as answered in the chat.

The world is the lived-in Trailhead project from test_reviews: rules, a decision, a task with
acceptance criteria in progress, and a second task waiting in To do."""

from pathlib import Path

import pytest

from app.services.review_waits import waits_on_person
from tests.conftest import app_client
from tests.test_mcp import agent, call
from tests.test_reviews import brief, submit_review, world

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "title",
    [
        "Badge mockup ready for review",
        "Trail map: two layouts sketched, waiting for Sam's pick",
        "Plan written, waiting for the owner's approval",
        "Fix built and checked, waiting for commit OK",
        "Camp sign mockup shown, waiting for the OK",
        "Three legend styles ready for Sam",
        "Admin panel scope awaiting approval",
        "Route sketch sent for approval",
        "Research done, needs your decision on the map size",
        "Badge colours mocked up, waiting on Sam",
        "Badge plan written, waiting for your OK to commit",
        "Map ready for review (round 2)",
        "Legend sketched - waiting for approval before the build",
    ],
)
def test_titles_that_wait_for_the_person(title: str) -> None:
    assert waits_on_person(title)


@pytest.mark.parametrize(
    "title",
    [
        "Badge built from the approved mockup",
        "Waiting for CI before the merge",
        "CAMP-4 merged; waiting for CAMP-7 before one push",
        "Waiting for the build to finish",
        "Victory screen waits for every camper to arrive",
        # The ask word only names something else here.
        "Merged CAMP-3 and CAMP-4 into main; waiting for the Review hand-over PRs",
        "Waiting for test results from CI",
        "Legend done; waiting for the review screen to load",
        "Sam's notes applied to the legend",
        "",
    ],
)
def test_titles_that_do_not(title: str) -> None:
    assert not waits_on_person(title)


def test_the_agent_saying_so_wins_over_the_title() -> None:
    assert waits_on_person("Legend drawn", said=True)
    assert not waits_on_person("Legend ready for review", said=False)


async def test_a_waiting_note_waits_in_review_once_and_moving_on_settles_it(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
    pid, task = w["pid"], w["task"]
    url = f"/api/projects/{pid}/tasks/{task}/review"
    async with agent(database_url) as session:
        error, out = await call(
            session,
            "brain_create_checkpoint",
            project="trailhead",
            task=task,
            title="Badge mockup ready for review",
            summary="Two badge styles on the camp card.",
            completed_work="- Mockup A: number in a pill\n- Mockup B: dots",
            next_steps="Build the style the person picks.",
        )
        assert not error and out["task"] == task and "waits for the person" in out["review"]

        async with app_client(database_url) as client:
            assert (await client.get(f"/api/projects/{pid}/tasks/{task}")).json()[
                "status"
            ] == "blocked"
            [item] = (await client.get("/api/reviews")).json()["waiting"]
            assert item["ref"] == task and item["question"] is True
            current = (await client.get(url)).json()["current"]
            assert current["kind"] == "question" and current["from_note"] is True
            assert current["summary"] == "Badge mockup ready for review"
            assert "Two badge styles" in current["details"]
            assert "**Done so far**" in current["details"]

        # A newer version of the same wait updates that question instead of adding one.
        error, out = await call(
            session,
            "brain_create_checkpoint",
            project="trailhead",
            title="Badge mockup v2: dots bigger, waiting for approval",
        )
        assert not error and out["task"] == task and "review" in out
        async with app_client(database_url) as client:
            [item] = (await client.get("/api/reviews")).json()["waiting"]
            detail = (await client.get(url)).json()
            assert detail["current"]["round"] == 1 and detail["earlier"] == []
            assert detail["current"]["summary"].startswith("Badge mockup v2")

        # The person answered in the chat; the agent goes on and says what it did.
        error, out = await call(
            session,
            "brain_create_checkpoint",
            project="trailhead",
            title="Badge built with the dots style",
            completed_work="- Dots badge on every camp card",
        )
        assert not error and "review" not in out

    async with app_client(database_url) as client:
        assert (await client.get(f"/api/projects/{pid}/tasks/{task}")).json()[
            "status"
        ] == "in_progress"
        assert (await client.get("/api/reviews")).json()["waiting"] == []
        current = (await client.get(url)).json()["current"]
        assert (current["status"], current["moved_to"]) == ("answered", "chat")
    # The agent already had that answer: the brief does not hand it over again.
    assert "ANSWERED IN REVIEW" not in brief(database_url, pid)


async def test_the_person_approves_a_wait_or_accepts_it_as_done(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
    pid, task = w["pid"], w["task"]
    url = f"/api/projects/{pid}/tasks/{task}/review"
    async with agent(database_url) as session:
        await call(
            session,
            "brain_create_checkpoint",
            project="trailhead",
            task=task,
            title="Badge plan written, waiting for Sam's OK",
        )
    async with app_client(database_url) as client:
        # Approve and continue: no words needed, the task goes back to In progress.
        answered = await client.post(url + "/decision", json={"verdict": "approve"})
        assert answered.status_code == 200, answered.text
        current = answered.json()["current"]
        assert current["status"] == "answered" and current["comment"] == (
            "Approved. Go on as planned."
        )
        assert answered.json()["task_status"] == "in_progress"
    assert "Approved. Go on as planned." in brief(database_url, pid)

    async with agent(database_url) as session:
        await call(
            session,
            "brain_create_checkpoint",
            project="trailhead",
            task=task,
            title="Badge built, ready for review",
            waiting_for_person=True,
        )
    async with app_client(database_url) as client:
        detail = (await client.get(url)).json()
        assert detail["current"]["round"] == 2 and detail["current"]["from_note"]
        # The wait was finished work: accept it and the task is done.
        accepted = await client.post(url + "/decision", json={"verdict": "accept"})
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["task_status"] == "completed"
        assert accepted.json()["current"]["status"] == "accepted"
        assert (await client.get("/api/reviews")).json()["waiting"] == []


async def test_a_wait_without_a_task_starts_one_task_for_the_session(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
        before = len((await client.get(f"/api/projects/{w['pid']}/tasks")).json())
    async with agent(database_url) as session:
        error, out = await call(
            session,
            "brain_create_checkpoint",
            project="trailhead",
            title="Trail sign sketches",
            summary="Three sign shapes for the north trail.",
            waiting_for_person=True,
        )
        assert not error and "Moah started" in out["task_started"]
        started = out["task"]
        assert started not in (w["task"], w["other"]) and "review" in out
        # The same session's next note lands on that task and settles the wait.
        error, out = await call(
            session, "brain_create_checkpoint", project="trailhead", title="Round signs drawn"
        )
        assert not error and out["task"] == started
        # Saying it does not wait wins over a title that reads like it.
        error, out = await call(
            session,
            "brain_create_checkpoint",
            project="trailhead",
            title="Round signs ready for review",
            waiting_for_person=False,
        )
        assert not error and "review" not in out
    async with app_client(database_url) as client:
        tasks = (await client.get(f"/api/projects/{w['pid']}/tasks")).json()
        assert len(tasks) == before + 1
        made = (await client.get(f"/api/projects/{w['pid']}/tasks/{started}")).json()
        assert made["status"] == "in_progress" and "started-by-moah" in made["tags"]
        assert "Started by Project Moah" in made["description"]
        assert (await client.get("/api/reviews")).json()["waiting"] == []


async def test_a_note_never_replaces_what_already_waits(database_url: str, tmp_path: Path) -> None:
    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
    pid, task, other = w["pid"], w["task"], w["other"]
    async with agent(database_url) as session:
        # The agent asked itself: its question stays as it asked it.
        await call(
            session,
            "brain_ask_person",
            project="trailhead",
            task=task,
            question="Should full camps show 0 or 'Full'?",
            options=["0", "Full"],
        )
        await call(
            session,
            "brain_create_checkpoint",
            project="trailhead",
            task=task,
            title="Badge waits for the person's choice",
        )
        # Work already handed over waits as work, not as a question.
        await call(session, "brain_update_task", project="trailhead", task=other, status="review")
        await call(
            session,
            "brain_create_checkpoint",
            project="trailhead",
            task=other,
            title="Legend done, waiting for review",
        )
    async with app_client(database_url) as client:
        mine = (await client.get(f"/api/projects/{pid}/tasks/{task}/review")).json()["current"]
        assert mine["summary"].startswith("Should full camps") and not mine["from_note"]
        theirs = (await client.get(f"/api/projects/{pid}/tasks/{other}/review")).json()
        assert theirs["current"]["kind"] == "work" and theirs["task_status"] == "review"


async def test_handing_over_after_a_wait_keeps_the_wait_in_history(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
    pid, task = w["pid"], w["task"]
    async with agent(database_url) as session:
        await call(
            session,
            "brain_create_checkpoint",
            project="trailhead",
            task=task,
            title="Badge mockup ready for review",
        )
    submit_review(database_url, pid, task)
    async with app_client(database_url) as client:
        detail = (await client.get(f"/api/projects/{pid}/tasks/{task}/review")).json()
        assert detail["task_status"] == "review" and detail["current"]["kind"] == "work"
        assert detail["current"]["round"] == 2
        [earlier] = detail["earlier"]
        assert (earlier["status"], earlier["moved_to"]) == ("answered", "chat")

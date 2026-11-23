"""What the person decides in Review reaches the chat that asked (chat_delivery.py, chat_wait.py).

The world is test_tool_hook's harbor-map project: an orchestrator and two sub-tasks, in one chat.
The Stop hook runs as a waiter with a fake clock and a fake sleep, so a day of waiting takes no
time, and the person's decision arrives in the middle of it through the real ReviewService (the
function behind the Review screen's buttons). One test runs the real command as a subprocess."""

import io
import itertools
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.conftest import app_client
from tests.test_chat_questions import REAL_QUESTION, SESSION, database, run_hook
from tests.test_mcp import agent
from tests.test_tool_hook import CODEX, OTHER, TILES, call, sandbox

pytestmark = pytest.mark.anyio

BACKEND = Path(__file__).resolve().parents[1]
PARENT = 4242  # the agent's process id, made up
HAND_OVER = "Tiles are cut and named by zoom level."


class Clock:
    """A clock that moves only when the hook sleeps. ``at[n]`` runs after the n-th sleep: what
    the person does while the hook waits."""

    def __init__(self) -> None:
        self.now = datetime.now(UTC)
        self.started = self.now
        self.slept: list[float] = []
        self.at: dict[int, object] = {}

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += timedelta(seconds=seconds)
        if (action := self.at.get(len(self.slept))) is not None:
            action()


# ---- the world and what the agent and the person do in it ---------------------------------


async def world(database_url: str, tmp_path: Path) -> dict:
    async with app_client(database_url) as client:
        return await sandbox(client, tmp_path)


def ask(database_url: str, w: dict, ref: str, question: str = TILES, chat: str | None = SESSION):
    """The agent asks about a task. Returns the review's id."""
    from app.schemas.review import AskPerson
    from app.services.activity import acting_as
    from app.services.reviews import ReviewService

    payload = AskPerson(question=question, options=["PNG", "WebP"])
    with database(database_url) as session, acting_as("claude", "claude"):
        return ReviewService(session).ask(w["pid"], ref, payload, "claude", session_id=chat).id


def hand_over(database_url: str, w: dict, ref: str, chat: str | None = SESSION) -> str:
    """The agent hands a task over. Returns the review's id."""
    from app.schemas.review import ReviewSubmit
    from app.services.activity import acting_as
    from app.services.reviews import ReviewService

    payload = ReviewSubmit(summary=HAND_OVER, done=["Slicing", "Naming"])
    with database(database_url) as session, acting_as("claude", "claude"):
        return ReviewService(session).submit(w["pid"], ref, payload, "claude", session_id=chat).id


def note_wait(database_url: str, w: dict, ref: str, chat: str | None = SESSION) -> str:
    """The agent's checkpoint says it waits for the person: Moah opens a question for it in Review
    (the wait that can also be accepted as finished work). Returns the review's id."""
    from types import SimpleNamespace
    from uuid import uuid4

    from app.models.task import Task
    from app.services.activity import acting_as
    from app.services.reviews import ReviewService

    note = SimpleNamespace(
        id=str(uuid4()),
        title="Release notes drafted, waiting for the OK",
        summary="",
        completed_work="- Drafted",
        remaining_work="",
        problems="",
        next_steps="",
    )
    with database(database_url) as session, acting_as("claude", "claude"):
        task = session.query(Task).filter(Task.human_id == ref).one()
        found = ReviewService(session).wait_from_checkpoint(task, note, "claude", session_id=chat)
        return found.id


def decide(database_url: str, w: dict, ref: str, verdict: str, comment=None, file=None):
    """The person decides in Review (the buttons' own code), with a file attached if given.
    Returns what the Review screen gets back (the task's review detail)."""
    from app.schemas.review import ReviewDecision
    from app.services.activity import acting_as
    from app.services.reviews import ReviewService

    with database(database_url) as session, acting_as("human"):
        service = ReviewService(session)
        if file is not None:
            service.add_feedback(w["pid"], ref, file, "zoom-3.txt")
        return service.decide(w["pid"], ref, ReviewDecision(verdict=verdict, comment=comment))


def reopen(database_url: str, w: dict, ref: str, comment: str) -> None:
    from app.schemas.review import ReviewReopen
    from app.services.activity import acting_as
    from app.services.reviews import ReviewService

    with database(database_url) as session, acting_as("human"):
        ReviewService(session).reopen(w["pid"], ref, ReviewReopen(comment=comment))


def undo(database_url: str, w: dict, ref: str) -> None:
    from app.services.activity import acting_as
    from app.services.reviews import ReviewService

    with database(database_url) as session, acting_as("human"):
        ReviewService(session).undo_accept(w["pid"], ref)


def review_of(database_url: str, review_id: str) -> dict:
    from app.models.review import TaskReview

    with database(database_url) as session:
        row = session.get(TaskReview, review_id)
        return {
            "status": row.status,
            "comment": row.comment,
            "moved_to": row.moved_to,
            "session_id": row.session_id,
            "delivered_at": row.delivered_at,
        }


def waiting_rows(database_url: str, chat: str = SESSION) -> list[int]:
    from app.models.agent_session import AgentSessionEvent

    with database(database_url) as session:
        found = session.query(AgentSessionEvent.id).filter(
            AgentSessionEvent.session_id == chat, AgentSessionEvent.source == "waiting"
        )
        return [row for (row,) in found.order_by(AgentSessionEvent.id)]


def logged_errors(database_url: str) -> list[dict]:
    log = Path(database_url.removeprefix("sqlite:///")).parent / "logs" / "errors-mcp.log"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def person_writes(database_url: str, text: str, chat: str = SESSION) -> None:
    """The person writes in the chat: what the prompt hook does with the message (without the
    command line, which would read the message from standard input as the waiter's own does)."""
    from app.services.chat_questions import record_prompt

    with database(database_url) as session:
        record_prompt(session, "claude", {"session_id": chat, "prompt": text})


def hook_input(monkeypatch, capsys, database_url: str, **fields: object) -> None:
    """What Claude Code puts on a hook's standard input; and a clean slate for what it prints."""
    from app.mcp import cli

    capsys.readouterr()  # what building the world printed (the migrations log to standard error)
    monkeypatch.setenv("PROJECT_BRAIN_DATABASE_URL", database_url)
    monkeypatch.setattr(cli, "get_database_url", lambda: database_url)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": SESSION, **fields})))


def wait(
    database_url: str, monkeypatch, capsys, clock: Clock, message: str = "Done.", **options
) -> tuple[int, str]:
    """Run Claude Code's ``--hook wait`` for the chat on the fake clock, for a turn that ended on
    ``message`` (by default not on a question). Returns its exit code and what it wrote on
    standard error."""
    from app.services import chat_wait

    hook_input(
        monkeypatch, capsys, database_url, hook_event_name="Stop", last_assistant_message=message
    )
    # Never "on Windows", where the waiter would ask the system whether the made-up agent (4242)
    # lives and end at once: the tests that mean Windows say so (windows=True).
    options = {
        "clock": clock,
        "sleep": clock.sleep,
        "getppid": lambda: PARENT,
        "windows": False,
        **options,
    }
    code = chat_wait.before_loading(
        ["--agent", "claude", "--hook", "wait"], chat_wait.Run(**options)
    )
    printed = capsys.readouterr()
    assert printed.out == "", printed.out  # Claude Code adds a hook's output to the message
    return code, printed.err


def stop(
    database_url: str,
    monkeypatch,
    capsys,
    clock: Clock,
    message: str,
    flags=("--settle",),
    **fields,
) -> tuple[int, str]:
    """Run the Stop hook that records, as the entry point does: what can be settled before the
    database loads, then the command itself. Returns its exit code and standard error."""
    from app.mcp import cli
    from app.services import chat_wait

    hook_input(monkeypatch, capsys, database_url, last_assistant_message=message, **fields)
    argv = ["--agent", "claude", "--hook", "stop", *flags]
    run = chat_wait.Run(clock=clock, sleep=clock.sleep, getppid=lambda: PARENT)
    code = chat_wait.before_loading(argv, run)
    if code is None:
        code = cli.main(argv)
    printed = capsys.readouterr()
    assert printed.out == "", printed.out
    return code, printed.err


# ---- the waiter hands the chat what the person decided -------------------------------------


async def test_an_answer_given_in_review_wakes_the_chat_that_asked(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.services.chat_wait import POLL

    w = await world(database_url, tmp_path)
    sub = w["sub"]
    asked = ask(database_url, w, sub)
    clock = Clock()
    clock.at[2] = lambda: decide(database_url, w, sub, "answer", "WebP")

    code, text = wait(database_url, monkeypatch, capsys, clock)

    assert code == 2
    assert clock.slept == [POLL, POLL]  # looked every 2 seconds, found it on the third look
    assert text == (
        "Project Moah Review: the person decided in Review.\n\n"
        f'{sub} "Choose the tile format for map export"\n'
        f"You asked: {TILES}\n"
        "The person chose: WebP\n"
        "Next: carry on with the task using this answer. Do not ask it again: it is already "
        "recorded in Moah.\n\n"
        f"(Moah review ids: {asked})\n"
    )
    got = review_of(database_url, asked)
    assert got["status"] == "answered" and got["delivered_at"] is not None
    assert len(waiting_rows(database_url)) == 1  # the hook said it waited


async def test_a_typed_answer_and_an_approval_read_differently_from_a_chosen_option(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    w = await world(database_url, tmp_path)
    sub, notes = w["sub"], w["notes"]
    ask(database_url, w, sub)
    ask(database_url, w, notes, question="Ship the notes in English only?", chat=SESSION)
    clock = Clock()

    def answer() -> None:
        decide(database_url, w, sub, "answer", "WebP, but keep PNG for the icons.")
        decide(database_url, w, notes, "approve")

    clock.at[1] = answer
    code, text = wait(database_url, monkeypatch, capsys, clock)

    assert code == 2
    assert "The person answered: WebP, but keep PNG for the icons." in text
    assert "The person approved: go on as planned." in text
    assert text.count(f"{sub} ") == 1 and text.count(f"{notes} ") == 1  # one message for both
    assert "Next: carry on with the task as planned." in text


async def test_a_send_back_hands_over_the_comments_and_says_a_file_came_with_them(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    w = await world(database_url, tmp_path)
    notes = w["notes"]
    sent = hand_over(database_url, w, notes)
    clock = Clock()
    clock.at[1] = lambda: decide(
        database_url, w, notes, "reject", "The notes miss offline mode.", file=b"zoom 3 is blurry"
    )

    code, text = wait(database_url, monkeypatch, capsys, clock)

    assert code == 2
    assert text == (
        "Project Moah Review: the person decided in Review.\n\n"
        f'{notes} "Write the release notes"\n'
        f"You handed over: {HAND_OVER}\n"
        "The person sent it back with comments: The notes miss offline mode.\n"
        "Files attached to the comments: 1. Read them with brain_get_task (text files) and "
        "brain_view_images (pictures).\n"
        "Next: work on these comments, then hand the task over again with brain_submit_review.\n\n"
        f"(Moah review ids: {sent})\n"
    )
    assert review_of(database_url, sent)["delivered_at"] is not None


async def test_accepting_a_report_with_a_comment_wakes_the_chat_that_handed_it_over(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.services.chat_wait import POLL

    w = await world(database_url, tmp_path)
    notes = w["notes"]
    sent = hand_over(database_url, w, notes)
    clock = Clock()
    # The report waits for the person: the waiter is alive when they accept, two looks later.
    clock.at[2] = lambda: decide(
        database_url, w, notes, "accept", "Good. Add the offline notes to the changelog too."
    )

    code, text = wait(database_url, monkeypatch, capsys, clock)

    assert code == 2
    assert clock.slept == [POLL, POLL]
    assert text == (
        "Project Moah Review: the person decided in Review.\n\n"
        f'{notes} "Write the release notes"\n'
        f"You handed over: {HAND_OVER}\n"
        f"The person accepted it and moved {notes} to Done, with this comment: "
        "Good. Add the offline notes to the changelog too.\n"
        "Next: the task is done. If the comment asks for more work, record it as a new task "
        "(brain_create_task) and do it there; otherwise just acknowledge it briefly.\n\n"
        f"(Moah review ids: {sent})\n"
    )
    got = review_of(database_url, sent)
    assert got["status"] == "accepted" and got["delivered_at"] is not None
    assert len(waiting_rows(database_url)) == 1  # the hook said it waited


async def test_accepting_a_report_without_a_comment_wakes_nobody(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    w = await world(database_url, tmp_path)
    notes = w["notes"]
    sent = hand_over(database_url, w, notes)
    clock = Clock()
    clock.at[1] = lambda: decide(database_url, w, notes, "accept")

    code, text = wait(database_url, monkeypatch, capsys, clock)

    assert (code, text) == (0, "")
    got = review_of(database_url, sent)
    assert (got["status"], got["delivered_at"]) == ("accepted", None)  # nothing was claimed
    assert len(waiting_rows(database_url)) == 1  # it was there, waiting, when the person accepted


async def test_an_acceptance_with_a_file_is_handed_over_with_or_without_words(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    w = await world(database_url, tmp_path)
    sub, notes = w["sub"], w["notes"]
    first = hand_over(database_url, w, notes)
    second = hand_over(database_url, w, sub)
    clock = Clock()

    def accept() -> None:
        decide(database_url, w, notes, "accept", "Ship it.", file=b"zoom 3 looks fine")
        decide(database_url, w, sub, "accept", file=b"a note for the next release")

    clock.at[1] = accept
    code, text = wait(database_url, monkeypatch, capsys, clock)

    assert code == 2
    files = (
        "Files attached to the comments: 1. Read them with brain_get_task (text files) and "
        "brain_view_images (pictures).\n"
    )
    assert text == (
        "Project Moah Review: the person decided in Review.\n\n"
        f'{notes} "Write the release notes"\n'
        f"You handed over: {HAND_OVER}\n"
        f"The person accepted it and moved {notes} to Done, with this comment: Ship it.\n"
        + files
        + "Next: the task is done. If the comment or the files ask for more work, record it as a "
        "new task (brain_create_task) and do it there; otherwise just acknowledge it briefly.\n\n"
        f'{sub} "Choose the tile format for map export"\n'
        f"You handed over: {HAND_OVER}\n"
        f"The person accepted it and moved {sub} to Done, with files and no words.\n"
        + files
        + "Next: the task is done. If the files ask for more work, record it as a new task "
        "(brain_create_task) and do it there; otherwise just acknowledge it briefly.\n\n"
        f"(Moah review ids: {first}, {second})\n"
    )


async def test_accepting_the_agents_note_as_finished_work_with_a_comment_wakes_the_chat(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    w = await world(database_url, tmp_path)
    notes = w["notes"]
    waiting = note_wait(database_url, w, notes)
    clock = Clock()
    clock.at[1] = lambda: decide(database_url, w, notes, "accept", "Looks done to me.")

    code, text = wait(database_url, monkeypatch, capsys, clock)

    assert code == 2
    assert text == (
        "Project Moah Review: the person decided in Review.\n\n"
        f'{notes} "Write the release notes"\n'
        "You asked: Release notes drafted, waiting for the OK\n"
        f"The person accepted your note and moved {notes} to Done, with this comment: "
        "Looks done to me.\n"
        "Next: the task is done. If the comment asks for more work, record it as a new task "
        "(brain_create_task) and do it there; otherwise just acknowledge it briefly.\n\n"
        f"(Moah review ids: {waiting})\n"
    )
    assert review_of(database_url, waiting)["status"] == "accepted"
    # Without words, the same acceptance wakes nobody.
    other = note_wait(database_url, w, w["sub"])
    decide(database_url, w, w["sub"], "accept")
    assert review_of(database_url, other)["delivered_at"] is None
    assert wait(database_url, monkeypatch, capsys, Clock()) == (0, "")


async def test_an_acceptance_the_waiter_missed_is_handed_over_at_the_next_message(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.services import chat_delivery

    w = await world(database_url, tmp_path)
    notes = w["notes"]
    sent = hand_over(database_url, w, notes)
    decide(database_url, w, notes, "accept", "Good.")
    monkeypatch.setattr(chat_delivery.time, "sleep", lambda _: None)
    capsys.readouterr()

    told = run_hook(
        monkeypatch,
        capsys,
        database_url,
        "prompt",
        {"prompt": "Hi."},
        code=2,
        flags=("--deliver",),
    )

    assert f"The person accepted it and moved {notes} to Done, with this comment: Good." in told
    assert review_of(database_url, sent)["delivered_at"] is not None


async def test_a_report_without_a_chat_is_stamped_for_an_acceptance_that_has_words_only(
    database_url: str, tmp_path: Path
) -> None:
    w = await world(database_url, tmp_path)
    sub, notes = w["sub"], w["notes"]
    await _chat_works_on(database_url, w, sub)
    await _chat_works_on(database_url, w, notes)
    silent = hand_over(database_url, w, sub, chat=None)
    said = hand_over(database_url, w, notes, chat=None)
    decide(database_url, w, sub, "accept")
    decide(database_url, w, notes, "accept", "Good.")
    assert review_of(database_url, silent)["session_id"] is None  # nobody is woken for this
    assert review_of(database_url, said)["session_id"] == SESSION


async def test_the_decision_says_whether_the_round_has_a_chat_to_tell(
    database_url: str, tmp_path: Path
) -> None:
    """What the Review screen tells the person about their comment depends on it: a chat that is
    known after the decision (the round's own, or the one found working on the task) gets it."""
    w = await world(database_url, tmp_path)
    sub, notes, orchestrator = w["sub"], w["notes"], w["orchestrator"]
    await _chat_works_on(database_url, w, notes)
    hand_over(database_url, w, sub)  # the report knows its chat
    hand_over(database_url, w, notes, chat=None)  # a chat is found for it when decided
    hand_over(database_url, w, orchestrator, chat=None)  # nobody worked on it that Moah knows

    assert decide(database_url, w, sub, "accept", "Good.").current.chat_known is True
    assert decide(database_url, w, notes, "accept", "Good.").current.chat_known is True
    assert decide(database_url, w, orchestrator, "accept", "Good.").current.chat_known is False
    # The same through the service that serves the screen later.
    from app.services.reviews import ReviewService

    with database(database_url) as session:
        service = ReviewService(session)
        got = {ref: service.detail(w["pid"], ref).current.chat_known for ref in (sub, notes)}
        assert got == {sub: True, notes: True}
        assert service.detail(w["pid"], orchestrator).current.chat_known is False


async def test_a_question_and_an_unstamped_report_say_the_same_about_their_chat(
    database_url: str, tmp_path: Path
) -> None:
    from app.services.reviews import ReviewService

    w = await world(database_url, tmp_path)
    sub, notes = w["sub"], w["notes"]
    ask(database_url, w, sub)  # stamped by the chat that asked
    ask(database_url, w, notes, chat=None)  # an older question that remembers no chat
    with database(database_url) as session:
        service = ReviewService(session)
        assert service.detail(w["pid"], sub).current.chat_known is True
        assert service.detail(w["pid"], notes).current.chat_known is False
    assert decide(database_url, w, sub, "answer", "WebP").current.chat_known is True
    assert decide(database_url, w, notes, "answer", "PNG").current.chat_known is False


async def test_an_acceptance_that_was_handed_over_is_new_again_when_undone_or_reopened(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.services.chat_delivery import deliver, undelivered

    w = await world(database_url, tmp_path)
    sub, notes = w["sub"], w["notes"]
    handed: list[str] = []
    for ref in (sub, notes):
        hand_over(database_url, w, ref)
        decide(database_url, w, ref, "accept", "Good.")
    with database(database_url) as session:
        assert deliver(session, SESSION, handed.append)  # both, in one message
        assert undelivered(session, SESSION) == []
    assert len(handed) == 1 and handed[0].count("The person accepted it") == 2

    # Taken back within minutes: the next decision on that round is one to hand over.
    undo(database_url, w, sub)
    decide(database_url, w, sub, "reject", "Not yet: the tiles are blurry.")
    # Accepted work the person reopens later: the same.
    reopen(database_url, w, notes, "Offline mode is missing.")
    with database(database_url) as session:
        found = undelivered(session, SESSION)
        text = "\n".join(f"{r.status}: {r.comment}" for r in found)
    assert text == (
        "rejected: Not yet: the tiles are blurry.\nrejected: Offline mode is missing."
    ), text


async def test_accepted_work_the_person_reopens_reaches_the_chat_that_handed_it_over(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    w = await world(database_url, tmp_path)
    sub, notes = w["sub"], w["notes"]
    sent = hand_over(database_url, w, notes)
    decide(database_url, w, notes, "accept")
    ask(database_url, w, sub)  # keeps the chat waiting
    clock = Clock()
    clock.at[2] = lambda: reopen(database_url, w, notes, "Offline mode is still missing.")

    code, text = wait(database_url, monkeypatch, capsys, clock)

    assert code == 2
    assert "The person sent it back with comments: Offline mode is still missing." in text
    assert f"(Moah review ids: {sent})" in text
    assert review_of(database_url, sent)["delivered_at"] is not None


async def test_an_answer_given_in_the_chat_ends_the_wait_and_nothing_is_handed_over(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    w = await world(database_url, tmp_path)
    sub = w["sub"]
    asked = ask(database_url, w, sub)
    clock = Clock()
    clock.at[1] = lambda: run_hook(
        monkeypatch, capsys, database_url, "prompt", {"prompt": "WebP, and say so in the notes."}
    )

    code, text = wait(database_url, monkeypatch, capsys, clock)

    assert (code, text) == (0, "")
    got = review_of(database_url, asked)
    assert (got["status"], got["moved_to"], got["delivered_at"]) == ("answered", "chat", None)


async def test_a_question_that_was_replaced_ends_the_wait(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.schemas.task import TaskUpdate
    from app.services.activity import acting_as
    from app.services.tasks import TaskService

    w = await world(database_url, tmp_path)
    sub = w["sub"]
    asked = ask(database_url, w, sub)

    def agent_goes_on() -> None:
        with database(database_url) as session, acting_as("claude", "claude"):
            TaskService(session).update(w["pid"], sub, TaskUpdate(status="in_progress"))

    clock = Clock()
    clock.at[1] = agent_goes_on
    code, text = wait(database_url, monkeypatch, capsys, clock)

    assert (code, text) == (0, "")
    assert review_of(database_url, asked)["status"] == "replaced"
    assert review_of(database_url, asked)["delivered_at"] is None


async def test_a_turn_that_ended_on_a_question_is_waited_for_while_the_record_hook_writes_it(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.services.chat_wait import GRACE, POLL

    await world(database_url, tmp_path)
    clock = Clock()

    code, text = wait(database_url, monkeypatch, capsys, clock, message=REAL_QUESTION)

    assert (code, text) == (0, "")
    assert sum(clock.slept) == GRACE == 30 and set(clock.slept) == {POLL}  # looked all that time
    assert waiting_rows(database_url) == []  # and it never had anything to wait for


async def test_a_question_the_record_hook_writes_a_few_seconds_later_is_still_waited_for(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    """The two Stop commands run side by side: the waiter may look before the question is there
    (or before the database is, on a first run)."""
    w = await world(database_url, tmp_path)
    sub = w["sub"]
    clock = Clock()
    clock.at[3] = lambda: ask(database_url, w, sub)
    clock.at[6] = lambda: decide(database_url, w, sub, "answer", "WebP")

    code, text = wait(database_url, monkeypatch, capsys, clock, message=REAL_QUESTION)

    assert code == 2 and "The person chose: WebP" in text
    assert len(clock.slept) == 6 and len(waiting_rows(database_url)) == 1


async def test_a_turn_without_a_question_looks_twice_and_ends_without_a_note(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.services.chat_wait import SETTLE

    await world(database_url, tmp_path)
    clock = Clock()

    code, text = wait(database_url, monkeypatch, capsys, clock)

    assert (code, text) == (0, "")
    assert clock.slept == [SETTLE] == [3.0]  # one look at once, one after the 3 seconds
    assert waiting_rows(database_url) == []


async def test_a_question_the_agent_asked_through_moah_is_stamped_late_and_still_waited_for(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    """The tool hook runs in the background: the stamp that links the question to this chat, or
    the task event, may land a second or two after the turn ended."""
    w = await world(database_url, tmp_path)
    sub = w["sub"]
    clock = Clock()
    clock.at[1] = lambda: ask(database_url, w, sub)  # during the 3 seconds
    clock.at[3] = lambda: decide(database_url, w, sub, "answer", "WebP")

    code, text = wait(database_url, monkeypatch, capsys, clock)

    assert code == 2 and "The person chose: WebP" in text
    assert clock.slept[0] == 3.0 and len(waiting_rows(database_url)) == 1


async def test_a_question_that_lands_after_the_second_look_is_left_to_the_prompt_hook(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    w = await world(database_url, tmp_path)
    clock = Clock()
    clock.at[1] = lambda: ask(database_url, w, w["sub"], chat=OTHER)  # not this chat's
    clock.at[2] = lambda: ask(database_url, w, w["notes"])  # this chat's, too late

    code, text = wait(database_url, monkeypatch, capsys, clock)

    assert (code, text) == (0, "") and clock.slept == [3.0]
    assert waiting_rows(database_url) == []


async def test_a_database_that_does_not_exist_yet_is_waited_for_too(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.services.chat_wait import GRACE

    database_url = f"sqlite:///{tmp_path / 'later.db'}"
    clock = Clock()

    code, text = wait(database_url, monkeypatch, capsys, clock, message=REAL_QUESTION)

    assert (code, text) == (0, "") and sum(clock.slept) == GRACE
    assert not (tmp_path / "later.db").exists()  # looking never makes one


async def test_a_task_waiting_for_review_without_a_stored_report_keeps_the_wait_going(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    """The agent moved the task to Review without writing a report: Review drafts one, and it
    is stored when the person decides. The task is the chat's, so the decision is its too."""
    from app.models.agent_session import AgentSessionEvent
    from app.models.task import Task
    from app.schemas.task import TaskUpdate
    from app.services.activity import acting_as
    from app.services.tasks import TaskService

    w = await world(database_url, tmp_path)
    notes = w["notes"]
    with database(database_url) as session:
        task = session.query(Task).filter(Task.human_id == notes).one()
        session.add(
            AgentSessionEvent(
                agent="claude",
                session_id=SESSION,
                project_id=w["pid"],
                task_id=task.id,
                source="task",
                created_at=datetime.now(UTC),
            )
        )
        session.commit()
        with acting_as("claude", "claude"):
            TaskService(session).update(w["pid"], notes, TaskUpdate(status="review"))
    clock = Clock()
    clock.at[2] = lambda: decide(database_url, w, notes, "reject", "Add the offline mode.")

    code, text = wait(database_url, monkeypatch, capsys, clock)

    assert code == 2
    assert "The person sent it back with comments: Add the offline mode." in text


# ---- a waiter that must not deliver ------------------------------------------------------


async def test_a_newer_waiter_for_the_same_chat_takes_over(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.services import chat_wait

    w = await world(database_url, tmp_path)
    sub = w["sub"]
    asked = ask(database_url, w, sub)
    clock = Clock()
    path = chat_wait.database_file({"PROJECT_BRAIN_DATABASE_URL": database_url})
    clock.at[1] = lambda: chat_wait.register(path, "claude", SESSION, clock())
    clock.at[2] = lambda: decide(database_url, w, sub, "answer", "WebP")

    code, text = wait(database_url, monkeypatch, capsys, clock)

    assert (code, text) == (0, "")  # the newer waiter hands it over, not this one
    assert review_of(database_url, asked)["delivered_at"] is None
    assert len(waiting_rows(database_url)) == 1  # and only its note is left


async def test_the_wait_ends_before_the_hook_is_stopped_at_its_timeout(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.services.chat_wait import WAIT_LIMIT

    assert WAIT_LIMIT == timedelta(hours=23, minutes=30)  # Claude Code stops a hook at 24 hours
    w = await world(database_url, tmp_path)
    asked = ask(database_url, w, w["sub"])
    clock = Clock()

    code, text = wait(database_url, monkeypatch, capsys, clock, poll=3600.0)

    assert (code, text) == (0, "")
    assert timedelta(hours=23, minutes=30) <= clock.now - clock.started < timedelta(hours=25)
    decide(database_url, w, w["sub"], "answer", "WebP")  # too late for this waiter
    assert review_of(database_url, asked)["delivered_at"] is None


async def test_a_waiter_whose_agent_is_gone_hands_nothing_over(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    w = await world(database_url, tmp_path)
    sub = w["sub"]
    asked = ask(database_url, w, sub)
    clock = Clock()
    clock.at[1] = lambda: decide(database_url, w, sub, "answer", "WebP")

    # The agent's process ends while the person answers: the hook's parent is no longer it.
    code, text = wait(
        database_url,
        monkeypatch,
        capsys,
        clock,
        getppid=lambda: PARENT if not clock.slept else 1,
    )

    assert (code, text) == (0, "")
    assert review_of(database_url, asked)["delivered_at"] is None

    # And the moment before it writes: it goes between the look and the delivery.
    answers = itertools.chain([PARENT, PARENT], itertools.repeat(1))
    clock = Clock()
    code, text = wait(database_url, monkeypatch, capsys, clock, getppid=lambda: next(answers))
    assert (code, text) == (0, "")
    assert review_of(database_url, asked)["delivered_at"] is None


class Kernel32:
    """The three Windows functions the parent check calls, answering what a test says."""

    def __init__(self, handle: int, waited: int, wait_fails: bool = False) -> None:
        self.handle, self.waited, self.wait_fails, self.calls = handle, waited, wait_fails, []

    def OpenProcess(self, access: int, inherit: bool, pid: int) -> int:  # noqa: N802
        self.calls.append(("open", access, inherit, pid))
        return self.handle

    def WaitForSingleObject(self, handle: int, milliseconds: int) -> int:  # noqa: N802
        self.calls.append(("wait", handle, milliseconds))
        if self.wait_fails:
            raise OSError("the call failed")
        return self.waited

    def CloseHandle(self, handle: int) -> int:  # noqa: N802
        self.calls.append(("close", handle))
        return 1


def test_a_parent_on_windows_is_asked_for_since_its_id_never_changes_there() -> None:
    """Mocked, so it runs on any system. NOT verified on a real Windows machine."""
    from app.services.chat_wait import (
        ERROR_ACCESS_DENIED,
        SYNCHRONIZE,
        WAIT_TIMEOUT,
        Run,
        gone,
        process_alive,
    )

    assert SYNCHRONIZE == 0x00100000 and WAIT_TIMEOUT == 0x102 and ERROR_ACCESS_DENIED == 5

    def alive(kernel: Kernel32, error: int = 0) -> bool:
        return process_alive(99, (kernel, lambda: error))

    # A handle that can only wait, waited on for no time at all: it times out while it runs.
    running = Kernel32(7, WAIT_TIMEOUT)
    assert alive(running) is True
    assert running.calls == [("open", SYNCHRONIZE, False, 99), ("wait", 7, 0), ("close", 7)]
    # ...and is signalled once the process has ended; the handle is closed either way.
    ended = Kernel32(7, 0)
    assert alive(ended) is False and ended.calls[-1] == ("close", 7)
    failing = Kernel32(7, 0, wait_fails=True)
    with pytest.raises(OSError):
        alive(failing)
    assert failing.calls[-1] == ("close", 7)
    # No such process (invalid parameter): gone. One that is not ours to open: still running.
    absent = Kernel32(0, 0)
    assert alive(absent, error=87) is False and absent.calls == [("open", SYNCHRONIZE, False, 99)]
    assert alive(Kernel32(0, 0), error=ERROR_ACCESS_DENIED) is True

    # Windows asks; everywhere else the parent's id changing says it ended.
    assert gone(5, Run(windows=True, alive=lambda pid: pid == 5, getppid=lambda: 1)) is False
    assert gone(5, Run(windows=True, alive=lambda pid: False, getppid=lambda: 5)) is True
    assert gone(5, Run(windows=False, getppid=lambda: 5)) is False
    assert gone(5, Run(windows=False, getppid=lambda: 1)) is True
    assert Run().windows == (sys.platform == "win32")


async def test_a_waiter_on_windows_whose_agent_ended_hands_nothing_over(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    w = await world(database_url, tmp_path)
    sub = w["sub"]
    asked = ask(database_url, w, sub)
    clock = Clock()
    clock.at[1] = lambda: decide(database_url, w, sub, "answer", "WebP")
    asked_about: list[int] = []

    def alive(pid: int) -> bool:
        asked_about.append(pid)
        return not clock.slept  # until the person answers

    # Its parent id never changes on Windows, so a getppid() that says it did means nothing.
    code, text = wait(
        database_url, monkeypatch, capsys, clock, windows=True, alive=alive, getppid=lambda: PARENT
    )

    assert (code, text) == (0, "") and set(asked_about) == {PARENT}
    assert review_of(database_url, asked)["delivered_at"] is None


async def test_a_failure_never_wakes_the_chat(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    """Exit code 2 wakes the chat with whatever was written, so no error may ever end in it."""
    from app.services import chat_wait

    w = await world(database_url, tmp_path)
    sub = w["sub"]
    asked = ask(database_url, w, sub)

    def breaks(*_: object) -> None:
        raise RuntimeError("a failure in the middle of the wait")

    # The clock fails while the hook waits.
    class Failing(Clock):
        def __call__(self) -> datetime:
            if len(self.slept) >= 2:
                raise OSError("the clock failed")
            return super().__call__()

    failing = Failing()
    code, text = wait(database_url, monkeypatch, capsys, failing, sleep=failing.sleep)
    assert (code, text) == (0, "") and len(failing.slept) == 2
    assert [e["message"] for e in logged_errors(database_url)] == ["wait hook: OSError"]

    # Looking at Review fails.
    with monkeypatch.context() as patch:
        patch.setattr(chat_wait, "deliverable_ids", breaks)
        code, text = wait(database_url, monkeypatch, capsys, Clock())
    assert (code, text) == (0, "")

    # The person answers, and the callback that hands the decision over fails.
    clock = Clock()
    clock.at[1] = lambda: decide(database_url, w, sub, "answer", "WebP")
    code, text = wait(database_url, monkeypatch, capsys, clock, deliver=breaks)
    assert (code, text) == (0, "")

    # Standard error is closed (the agent is gone): the decision is taken back, not lost.
    def closed(_: str) -> None:
        raise BrokenPipeError

    code, text = wait(database_url, monkeypatch, capsys, Clock(), write=closed)
    assert (code, text) == (0, "")
    assert review_of(database_url, asked)["delivered_at"] is None
    assert [e["message"] for e in logged_errors(database_url)] == [
        "wait hook: OSError",
        "wait hook: RuntimeError",
        "wait hook: RuntimeError",
        "wait hook: BrokenPipeError",
    ]  # each failure said so, quietly


async def test_the_hook_that_records_never_exits_with_2_either(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.services import chat_questions

    await world(database_url, tmp_path)

    def breaks(*_: object) -> None:
        raise RuntimeError("recording failed")

    monkeypatch.setitem(chat_questions.HOOKS, "stop", breaks)
    code, text = stop(database_url, monkeypatch, capsys, Clock(), REAL_QUESTION)
    assert code == 0 and "Project Moah stop hook: recording failed" in text


async def test_the_decision_is_handed_over_once_when_the_waiter_and_the_prompt_hook_race(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.services.chat_delivery import deliver

    w = await world(database_url, tmp_path)
    sub = w["sub"]
    asked = ask(database_url, w, sub)
    from_prompt_hook: list[str] = []

    def prompt_hook_gets_there_first() -> None:
        decide(database_url, w, sub, "answer", "WebP")
        with database(database_url) as session:
            assert deliver(session, SESSION, from_prompt_hook.append)

    clock = Clock()
    clock.at[1] = prompt_hook_gets_there_first
    code, text = wait(database_url, monkeypatch, capsys, clock)

    assert (code, text) == (0, "")  # the waiter found nothing left: it ended quietly
    assert len(from_prompt_hook) == 1 and asked in from_prompt_hook[0]


async def test_decisions_are_never_handed_over_twice_by_callers_that_run_at_once(
    database_url: str, tmp_path: Path
) -> None:
    from app.services.chat_delivery import deliver, delivery_ids

    w = await world(database_url, tmp_path)
    refs = [w["orchestrator"], w["sub"], w["notes"]]
    wanted = {ask(database_url, w, ref, question=f"Question {n}?") for n, ref in enumerate(refs)}
    for ref in refs:
        decide(database_url, w, ref, "answer", "Yes.")
    handed: list[str] = []
    gate = threading.Barrier(4)

    def caller() -> None:
        with database(database_url) as session:
            gate.wait()
            deliver(session, SESSION, handed.append)

    threads = [threading.Thread(target=caller) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    ids = [one for text in handed for one in delivery_ids(text)]
    assert sorted(ids) == sorted(wanted)  # each of the three, once


async def test_the_prompt_hook_hands_over_what_no_waiter_did_and_codex_gets_it_as_output(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.mcp import cli
    from app.services import chat_delivery

    w = await world(database_url, tmp_path)
    sub, notes = w["sub"], w["notes"]
    asked = ask(database_url, w, sub)
    ask(database_url, w, notes, question="Ship in English only?", chat=CODEX)
    decide(database_url, w, sub, "answer", "WebP")
    decide(database_url, w, notes, "answer", "Yes.")
    slept: list[float] = []
    monkeypatch.setattr(chat_delivery.time, "sleep", slept.append)
    capsys.readouterr()  # what building the world printed

    # The hook line Connect wrote before this version (a plain background hook, no --deliver):
    # an exit code 2 from it would be lost, so it hands over nothing and claims nothing.
    assert run_hook(monkeypatch, capsys, database_url, "prompt", {"prompt": "Hi."}) == ""
    assert slept == [] and review_of(database_url, asked)["delivered_at"] is None

    # Claude Code, with --deliver (written for a hook that wakes the chat with exit code 2): the
    # person writes in the chat, and the chat is woken with what they decided in Review.
    flags = ("--deliver",)
    told = run_hook(
        monkeypatch, capsys, database_url, "prompt", {"prompt": "Hi."}, code=2, flags=flags
    )
    assert "The person chose: WebP" in told and "Ship in English" not in told
    assert slept == [chat_delivery.SETTLE]  # a waiter that still runs goes first
    # Delivered once: the next message gets nothing, and waits for nothing.
    assert (
        run_hook(monkeypatch, capsys, database_url, "prompt", {"prompt": "And?"}, flags=flags) == ""
    )
    assert slept == [chat_delivery.SETTLE]
    assert review_of(database_url, asked)["delivered_at"] is not None

    # Codex, without any flag: the hook's plain output is added to the model's context (its hook
    # is not a background one); the exit code stays 0.
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(json.dumps({"session_id": CODEX, "prompt": "Carry on."}))
    )
    assert cli.main(["--agent", "codex", "--hook", "prompt"]) == 0
    printed = capsys.readouterr()
    assert printed.out.startswith(chat_delivery.DELIVERY_MARKER)
    assert "The person answered: Yes." in printed.out and printed.err == ""
    assert slept == [chat_delivery.SETTLE]  # Codex's hook is not in the background: no wait


async def test_the_prompt_hook_never_exits_with_2_for_a_failure(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.mcp import cli
    from app.services import chat_delivery

    w = await world(database_url, tmp_path)
    asked = ask(database_url, w, w["sub"])
    decide(database_url, w, w["sub"], "answer", "WebP")
    monkeypatch.setattr(chat_delivery.time, "sleep", lambda _: None)

    def closed(_: str) -> None:
        raise BrokenPipeError

    monkeypatch.setattr(chat_delivery, "write_stderr", closed)
    monkeypatch.setattr(cli, "get_database_url", lambda: database_url)
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(json.dumps({"session_id": SESSION, "prompt": "x"}))
    )

    assert cli.main(["--agent", "claude", "--hook", "prompt", "--deliver"]) == 0
    assert "Project Moah prompt hook" in capsys.readouterr().err
    assert review_of(database_url, asked)["delivered_at"] is None  # still there for next time


async def test_no_other_agent_is_handed_a_decision_by_the_prompt_hook(
    database_url: str, tmp_path: Path
) -> None:
    from app.services.chat_delivery import prompt_delivery

    w = await world(database_url, tmp_path)
    asked = ask(database_url, w, w["sub"])
    decide(database_url, w, w["sub"], "answer", "WebP")
    with database(database_url) as session:
        for name in ("cursor", "agent", ""):
            assert prompt_delivery(session, name, {"session_id": SESSION}, wake=True) == 0
        assert prompt_delivery(session, "claude", {"session_id": SESSION}) == 0  # no --deliver
        for wrong in ({"session_id": "not a session id"}, {}):
            assert prompt_delivery(session, "claude", wrong, wake=True) == 0
    assert review_of(database_url, asked)["delivered_at"] is None


def test_the_stop_hook_keeps_its_fast_path_and_only_the_wait_hook_waits(monkeypatch) -> None:
    from app.services.chat_wait import before_loading
    from app.services.hook_text import hook_agent, hook_kind, nothing_to_record

    assert hook_agent([]) == "claude" and hook_agent(["--agent", "agent"]) == "claude"
    assert hook_agent(["--agent=Codex"]) == "codex"
    assert hook_agent(["--agent", "claude", "--agent", " Codex "]) == "codex"
    assert hook_kind(["--hook", "stop"]) == "stop"
    assert hook_kind(["--brief"]) is None and hook_kind(["--hook"]) is None

    def hook_gets(message: str) -> None:
        payload = {"session_id": SESSION, "last_assistant_message": message}
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))

    # A turn that did not end on a question ends before the database loads, for either agent,
    # with or without --settle (which waits only when there is something to record).
    for agent_name in ("claude", "codex"):
        for flags in ([], ["--settle"]):
            hook_gets("All done.")
            argv = ["--agent", agent_name, "--hook", "stop", *flags]
            assert nothing_to_record(argv) is True
            assert before_loading(argv) == 0
    # One that did goes on to record it (a synchronous line, without the flag, at once).
    hook_gets(REAL_QUESTION)
    assert before_loading(["--agent", "codex", "--hook", "stop"]) is None
    # Every other command goes on to the full command (a tool call that is not Moah's does not).
    for argv in ([], ["--brief"], ["--hook", "prompt"]):
        hook_gets("All done.")
        assert before_loading(argv) is None, argv
    hook_gets("All done.")
    assert before_loading(["--agent", "codex", "--hook", "tool"]) == 0
    # Only Claude Code's chat is woken by a waiter so far: Codex's ends at once.
    assert before_loading(["--agent", "codex", "--hook", "wait"]) == 0


def test_a_command_line_argparse_refuses_never_wakes_a_chat_from_a_hook(monkeypatch) -> None:
    """argparse ends a bad command line with exit code 2: that wakes Claude Code's chat."""
    from app.mcp import cli

    args = cli.parse_args(["--agent", "claude", "--hook", "stop", "--settle", "--deliver"])
    assert (args.hook, args.settle, args.deliver) == ("stop", True, True)
    args = cli.parse_args(["--agent", "claude", "--hook", "wait"])
    assert (args.hook, args.settle, args.deliver) == ("wait", False, False)
    assert cli.main(["--hook", "bogus"]) == 0
    assert cli.main(["--agent", "claude", "--hook", "stop", "--no-such-option"]) == 0
    with pytest.raises(SystemExit) as end:  # not a hook: as before
        cli.main(["--no-such-option"])
    assert end.value.code == 2


# ---- which chat a decision goes to ---------------------------------------------------------


async def test_a_decision_on_a_round_that_knows_no_chat_goes_to_the_chat_that_worked_on_the_task(
    database_url: str, tmp_path: Path
) -> None:
    from app.models.agent_session import AgentSessionEvent
    from app.models.task import Task

    async with app_client(database_url) as client:
        w = await sandbox(client, tmp_path)
        sub, notes, orchestrator = w["sub"], w["notes"], w["orchestrator"]
        base = f"/api/projects/{w['pid']}/tasks"
        with database(database_url) as session:
            ids = {
                ref: session.query(Task.id).filter(Task.human_id == ref).scalar()
                for ref in (sub, notes, orchestrator)
            }
            now = datetime.now(UTC)

            def worked(ref: str, chat: str, source: str, ago: timedelta, agent_name="claude"):
                session.add(
                    AgentSessionEvent(
                        agent=agent_name,
                        session_id=chat,
                        project_id=w["pid"],
                        task_id=ids[ref],
                        source=source,
                        created_at=now - ago,
                    )
                )

            # sub: two chats worked on it, the second a minute ago: that one.
            worked(sub, SESSION, "task", timedelta(hours=3))
            worked(sub, OTHER, "hook_task", timedelta(minutes=1))
            worked(sub, SESSION, "prompt", timedelta(seconds=5))  # a message names no work
            # notes: two chats touched it at the very same moment: no guess.
            worked(notes, SESSION, "task", timedelta(minutes=2))
            worked(notes, OTHER, "hook_task", timedelta(minutes=2))
            # orchestrator: only a chat from three days ago: too old.
            worked(orchestrator, SESSION, "task", timedelta(days=3))
            session.commit()
        for ref in (sub, notes, orchestrator):
            ask(database_url, w, ref, question=f"About {ref}?", chat=None)
            response = await client.post(
                f"{base}/{ref}/review/decision", json={"verdict": "answer", "comment": "Yes."}
            )
            assert response.status_code == 200, response.text

    from app.models.review import TaskReview

    with database(database_url) as session:
        got = {
            ref: session.query(TaskReview.session_id)
            .join(Task, Task.id == TaskReview.task_id)
            .filter(Task.human_id == ref)
            .scalar()
            for ref in (sub, notes, orchestrator)
        }
    assert got == {sub: OTHER, notes: None, orchestrator: None}


async def test_the_chat_is_found_for_accepted_work_that_is_reopened_and_not_for_an_acceptance(
    database_url: str, tmp_path: Path
) -> None:
    from app.models.agent_session import AgentSessionEvent
    from app.models.task import Task

    w = await world(database_url, tmp_path)
    notes = w["notes"]
    sent = hand_over(database_url, w, notes, chat=None)
    with database(database_url) as session:
        task_id = session.query(Task.id).filter(Task.human_id == notes).scalar()
        session.add(
            AgentSessionEvent(
                agent="claude",
                session_id=SESSION,
                project_id=w["pid"],
                task_id=task_id,
                source="hook_task",
                created_at=datetime.now(UTC),
            )
        )
        session.commit()

    decide(database_url, w, notes, "accept")
    assert review_of(database_url, sent)["session_id"] is None  # nobody is woken for this
    reopen(database_url, w, notes, "Offline mode is missing.")
    assert review_of(database_url, sent)["session_id"] == SESSION


# ---- what the Stop hook's waiter does with a turn's question -------------------------------


async def _chat_works_on(database_url: str, w: dict, ref: str) -> None:
    from app.models.agent_session import AgentSessionEvent
    from app.models.task import Task

    with database(database_url) as session:
        task_id = session.query(Task.id).filter(Task.human_id == ref).scalar()
        session.add(
            AgentSessionEvent(
                agent="claude",
                session_id=SESSION,
                project_id=w["pid"],
                task_id=task_id,
                source="task",
                created_at=datetime.now(UTC),
            )
        )
        session.commit()


async def test_a_message_the_person_writes_while_the_hook_settles_answers_the_question(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.models.review import TaskReview

    w = await world(database_url, tmp_path)
    await _chat_works_on(database_url, w, w["sub"])

    def recorded() -> list[tuple[str, str]]:
        with database(database_url) as session:
            return [(r.status, r.session_id) for r in session.query(TaskReview)]

    # Nobody writes: after 3 seconds the question the turn ended on is recorded, for this chat.
    clock = Clock()
    assert stop(database_url, monkeypatch, capsys, clock, REAL_QUESTION) == (0, "")
    assert clock.slept == [3.0] and recorded() == [("pending", SESSION)]
    with database(database_url) as session:
        session.query(TaskReview).delete()
        session.commit()

    # The person writes during the 3 seconds: that message is the answer, nothing is recorded.
    clock = Clock()
    clock.at[1] = lambda: person_writes(database_url, "Both, please.")
    assert stop(database_url, monkeypatch, capsys, clock, REAL_QUESTION) == (0, "")
    assert clock.slept == [3.0] and recorded() == []

    # The line Connect wrote before this version has no --settle: it does not wait, and records.
    clock = Clock()
    assert stop(database_url, monkeypatch, capsys, clock, REAL_QUESTION, flags=()) == (0, "")
    assert clock.slept == [] and recorded() == [("pending", SESSION)]


async def test_a_question_is_recorded_whatever_claude_codes_stop_flag_says(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    """``stop_hook_active`` is Claude Code's flag for a stop a hook already continued. Moah's hooks
    never block a stop, and the wake of the waiter may set it for the next turn's Stop hook."""
    from app.models.review import TaskReview

    w = await world(database_url, tmp_path)
    await _chat_works_on(database_url, w, w["sub"])

    code, text = stop(
        database_url, monkeypatch, capsys, Clock(), REAL_QUESTION, stop_hook_active=True
    )

    assert (code, text) == (0, "")
    with database(database_url) as session:
        assert session.query(TaskReview).filter(TaskReview.session_id == SESSION).count() == 1


async def test_a_database_from_before_this_version_gives_a_waiter_nothing_to_do(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    w = await world(database_url, tmp_path)
    ask(database_url, w, w["sub"])
    with sqlite3.connect(database_url.removeprefix("sqlite:///")) as db:
        db.execute("DROP INDEX ix_task_reviews_session")
        db.execute("ALTER TABLE task_reviews DROP COLUMN session_id")

    code, text = wait(database_url, monkeypatch, capsys, Clock())

    assert (code, text) == (0, "")  # the next hook that loads Project Moah migrates the file
    assert logged_errors(database_url) == []


# ---- the lean waiter against the rest of Project Moah --------------------------------------


async def test_the_waiters_queries_find_what_the_full_reader_finds(
    database_url: str, tmp_path: Path
) -> None:
    """chat_wait.DELIVERABLE is chat_delivery.undelivered in SQL: the waiter looks with the
    first and hands over with the second, so they must never disagree (a waiter that looks and
    finds what the second cannot claim would load Project Moah every two seconds)."""
    from app.models.review import ReviewFile, TaskReview
    from app.models.task import Task
    from app.services import chat_wait
    from app.services.chat_delivery import undelivered

    now = datetime.now(UTC)
    # (status, moved_to, comment, delivered, hours ago, chat, newer round, file, wanted)
    cases = [
        ("answered", None, "Yes.", False, 0, SESSION, False, False, True),
        ("rejected", None, "Fix it.", False, 0, SESSION, False, False, True),
        ("replaced", None, None, False, 0, SESSION, False, False, False),
        ("pending", None, None, False, 0, SESSION, False, False, False),
        ("answered", "chat", "In the chat.", False, 0, SESSION, False, False, False),
        ("answered", "in_progress", None, False, 0, SESSION, False, False, False),
        ("rejected", "in_progress", None, False, 0, SESSION, False, False, False),
        ("rejected", "in_progress", None, False, 0, SESSION, False, True, True),
        ("answered", None, "Yes.", True, 0, SESSION, False, False, False),
        ("answered", None, "Yes.", False, 8 * 24, SESSION, False, False, False),
        ("answered", None, "Yes.", False, 6 * 24, SESSION, False, False, True),
        ("answered", None, "Yes.", False, 0, OTHER, False, False, False),
        ("answered", None, "Yes.", False, 0, None, False, False, False),
        ("answered", None, "Yes.", False, 0, SESSION, True, False, False),
        ("answered", None, None, False, 0, SESSION, False, True, True),
        ("rejected", "in_progress", "Fix it.", False, 0, SESSION, False, False, True),
        ("rejected", None, "", False, 0, SESSION, False, False, True),
        # An acceptance is one to hand over when it came with words (a comment or a file).
        ("accepted", None, "Good.", False, 0, SESSION, False, False, True),
        ("accepted", None, None, False, 0, SESSION, False, True, True),
        ("accepted", None, "Good.", False, 0, SESSION, False, True, True),
        ("accepted", None, None, False, 0, SESSION, False, False, False),
        ("accepted", "completed", None, False, 0, SESSION, False, False, False),  # a board drag
        ("accepted", "completed", None, False, 0, SESSION, False, True, True),
        ("accepted", None, "Good.", True, 0, SESSION, False, False, False),
        ("accepted", None, "Good.", False, 8 * 24, SESSION, False, False, False),
        ("accepted", None, "Good.", False, 6 * 24, SESSION, False, False, True),
        ("accepted", None, "Good.", False, 0, OTHER, False, False, False),
        ("accepted", None, "Good.", False, 0, None, False, False, False),
        ("accepted", None, "Good.", False, 0, SESSION, True, False, False),
    ]
    async with app_client(database_url) as client:
        w = await sandbox(client, tmp_path)
        pid = w["pid"]
        made = {}
        for name in range(len(cases)):
            response = await client.post(
                f"/api/projects/{pid}/tasks", json={"title": f"Case {name}"}
            )
            made[name] = response.json()["id"]
    wanted: set[str] = set()
    with database(database_url) as session:
        for name, case in enumerate(cases):
            status, moved_to, comment, done, hours, chat, newer, has_file, expected = case
            at = now - timedelta(hours=hours, minutes=5)
            review = TaskReview(
                project_id=pid,
                task_id=made[name],
                round=1,
                agent="claude",
                kind="question" if status == "answered" else "work",
                status=status,
                summary=f"Case {name}",
                session_id=chat,
                comment=comment,
                moved_to=moved_to,
                reviewed_at=None if status == "pending" else at,
                delivered_at=at if done else None,
            )
            session.add(review)
            session.flush()
            if has_file:
                session.add(
                    ReviewFile(
                        project_id=pid,
                        review_id=review.id,
                        kind="feedback",
                        filename="a.txt",
                        media_type="text/plain",
                        size_bytes=1,
                        data=b"a",
                    )
                )
            if newer:
                session.add(
                    TaskReview(
                        project_id=pid,
                        task_id=made[name],
                        round=2,
                        agent="claude",
                        status="pending",
                        summary="Handed over again",
                        session_id=SESSION,
                    )
                )
            if expected:
                wanted.add(review.id)
        session.commit()
        assert session.query(Task).count() > len(cases)
        full = {row.id for row in undelivered(session, SESSION, now)}
    path = chat_wait.database_file({"PROJECT_BRAIN_DATABASE_URL": database_url})
    lean = set(chat_wait.deliverable_ids(path, SESSION, now))
    assert full == wanted and lean == wanted


async def test_the_waiter_sees_what_is_open_for_a_chat_as_chat_questions_does(
    database_url: str, tmp_path: Path
) -> None:
    from app.models.agent_session import AgentSessionEvent
    from app.models.task import Task
    from app.schemas.task import TaskUpdate
    from app.services import chat_wait
    from app.services.activity import acting_as
    from app.services.tasks import TaskService

    w = await world(database_url, tmp_path)
    path = chat_wait.database_file({"PROJECT_BRAIN_DATABASE_URL": database_url})
    sub, notes, orchestrator = w["sub"], w["notes"], w["orchestrator"]

    def is_open(chat: str = SESSION) -> bool:
        return chat_wait.has_open(path, "claude", chat)

    assert not is_open()
    ask(database_url, w, sub, chat=OTHER)
    assert not is_open() and is_open(OTHER)  # another chat's question is not ours
    ask(database_url, w, notes, chat=SESSION)
    assert is_open()  # our own, on a task that is not our session's

    # An unstamped question on the session's own task belongs to the chat that works on it.
    decide(database_url, w, notes, "answer", "Yes.")
    assert not is_open()
    with database(database_url) as session:
        task_id = session.query(Task.id).filter(Task.human_id == orchestrator).scalar()
        session.add(
            AgentSessionEvent(
                agent="claude",
                session_id=SESSION,
                project_id=w["pid"],
                task_id=task_id,
                source="hook_task",
                created_at=datetime.now(UTC),
            )
        )
        session.commit()
    ask(database_url, w, orchestrator, chat=None)
    assert is_open()
    decide(database_url, w, orchestrator, "answer", "Friday.")
    assert not is_open()

    # The session's task waits in Review and no report is stored for it.
    with database(database_url) as session, acting_as("claude", "claude"):
        TaskService(session).update(w["pid"], orchestrator, TaskUpdate(status="review"))
    assert is_open()
    hand_over(database_url, w, orchestrator, chat=OTHER)  # a report of another chat is stored
    assert not is_open()


def test_the_waiter_finds_the_database_the_way_the_app_does(tmp_path: Path, monkeypatch) -> None:
    from sqlalchemy.engine import make_url

    from app.core.config import get_database_url
    from app.services.chat_wait import database_file

    home = tmp_path / "home"
    home.mkdir()
    keys = ("PROJECT_BRAIN_DATABASE_URL", "PROJECT_BRAIN_DB_PATH", "XDG_DATA_HOME", "LOCALAPPDATA")
    cases = [
        {"PROJECT_BRAIN_DATABASE_URL": f"sqlite:///{tmp_path / 'a.db'}"},
        {"PROJECT_BRAIN_DATABASE_URL": "sqlite:///relative.db"},
        {"PROJECT_BRAIN_DB_PATH": "~/moah.db"},
        {"PROJECT_BRAIN_DB_PATH": str(tmp_path / "x" / ".." / "b.db")},
        {"XDG_DATA_HOME": str(tmp_path / "xdg")},
        {"XDG_DATA_HOME": "relative/xdg"},
        {},
    ]
    for case in cases:
        for key in keys:
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))  # Windows' name for it
        for key, value in case.items():
            monkeypatch.setenv(key, value)
        assert database_file() == Path(make_url(get_database_url()).database), case
    # A database that is no plain SQLite file: there is nothing to look at.
    for url in ("postgresql://u@h/db", "sqlite://", "sqlite:///:memory:", "sqlite:///a.db?x=1"):
        assert database_file({"PROJECT_BRAIN_DATABASE_URL": url}) is None, url


def test_what_the_waiter_spells_out_is_what_the_rest_of_project_moah_says() -> None:
    from app.services import agent_sessions, chat_wait, reviews

    assert chat_wait.ANSWERED_IN_CHAT == reviews.ANSWERED_IN_CHAT
    assert chat_wait.WAITING == agent_sessions.WAITING
    sources = ", ".join(
        f"'{source}'"
        for source in (agent_sessions.TASK, agent_sessions.HOOK_TASK, agent_sessions.PROMPT)
    )
    assert f"source IN ({sources})" in chat_wait.SESSION_TASK
    assert "r.moved_to != 'chat'" in chat_wait.DELIVERABLE
    assert chat_wait.DELIVERABLE_STATUSES == ("answered", "rejected", "accepted")
    statuses = ", ".join(f"'{status}'" for status in chat_wait.DELIVERABLE_STATUSES)
    assert f"r.status IN ({statuses})" in chat_wait.DELIVERABLE


async def test_a_waiting_note_is_no_task_no_claim_and_no_new_session(
    database_url: str, tmp_path: Path
) -> None:
    from app.models.agent_session import AgentSessionEvent
    from app.models.task import Task
    from app.services import chat_questions, chat_wait
    from app.services.agent_sessions import SESSION_ENV, SessionTracker, session_tasks

    w = await world(database_url, tmp_path)
    now = datetime.now(UTC)
    with database(database_url) as session:
        orchestrator = session.query(Task).filter(Task.human_id == w["orchestrator"]).one()
        notes = session.query(Task).filter(Task.human_id == w["notes"]).one()
        project = orchestrator.project_id
        for source, chat, task, ago in (
            ("startup", SESSION, None, 60),
            ("task", SESSION, orchestrator.id, 50),
        ):
            session.add(
                AgentSessionEvent(
                    agent="claude",
                    session_id=chat,
                    project_id=project,
                    task_id=task,
                    source=source,
                    agent_pid="111" if source == "startup" else None,
                    created_at=now - timedelta(seconds=ago),
                )
            )
        # What a waiter writes through chat_wait.register: ids and a time. And, to be sure
        # no reader looks at the source at all, a note that also names a task and a project.
        session.add(
            AgentSessionEvent(
                agent="claude",
                session_id=OTHER,
                project_id=project,
                task_id=notes.id,
                source="waiting",
                agent_pid="111",
                created_at=now,
            )
        )
        session.commit()
    path = chat_wait.database_file({"PROJECT_BRAIN_DATABASE_URL": database_url})
    chat_wait.register(path, "claude", SESSION, now)

    with database(database_url) as session:
        # The session's task, its project and its token use do not change.
        assert chat_questions.session_task(session, "claude", SESSION).id == orchestrator.id
        assert chat_questions.session_task(session, "claude", OTHER) is None
        assert chat_questions._project(session, "claude", OTHER, None) is None
        found = session_tasks(session, now - timedelta(hours=1), now + timedelta(hours=1))
        assert set(found) == {("claude", SESSION)}
        # A server that follows /clear is not moved to the waiting chat's id...
        tracker = SessionTracker("claude", {SESSION_ENV: SESSION})
        assert tracker.refresh(session) is False and tracker.current == SESSION
        # ...and one with no session id adopts nothing because of it.
        assert (
            SessionTracker("claude", {}).adopt(session, project, now + timedelta(seconds=20))
            is False
        )


# ---- the message itself --------------------------------------------------------------------


async def test_a_message_moah_handed_over_starts_a_turn_but_settles_and_names_nothing(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    """Codex's queue sends a delivery as a message, and Claude Code's wake may reach the prompt
    hook as one. It starts a turn, like any message; it is not the person's reply."""
    from app.models.agent_session import AgentSessionEvent
    from app.models.task import Task
    from app.services.chat_delivery import delivery_text, is_delivery, undelivered

    w = await world(database_url, tmp_path)
    root, sub, notes = str(w["root"]), w["sub"], w["notes"]
    answered = ask(database_url, w, sub)
    decide(database_url, w, sub, "answer", "WebP")
    waiting = ask(database_url, w, notes, question="Ship in English only?")
    with database(database_url) as session:
        text = delivery_text(session, undelivered(session, SESSION))
        sub_id = session.query(Task.id).filter(Task.human_id == sub).scalar()
    assert answered in text and sub in text

    def turns(chat: str) -> list[tuple[str, str | None]]:
        with database(database_url) as session:
            found = session.query(AgentSessionEvent).filter(
                AgentSessionEvent.session_id == chat, AgentSessionEvent.source == "prompt"
            )
            return [(e.source, e.task_id) for e in found.order_by(AgentSessionEvent.id)]

    # Control: the person's own message about a task names it for a chat that has none yet.
    message = f"Let's get {sub} done."
    run_hook(
        monkeypatch,
        capsys,
        database_url,
        "prompt",
        {"prompt": message, "cwd": root, "session_id": OTHER},
    )
    assert turns(OTHER) == [("prompt", sub_id)]

    # What Moah handed over names that task too, and the chat has a question any reply settles.
    run_hook(monkeypatch, capsys, database_url, "prompt", {"prompt": text, "cwd": root})
    assert turns(SESSION) == [("prompt", None)]  # the turn started; no task named
    assert review_of(database_url, waiting)["status"] == "pending"  # and nothing answered

    # Claude Code 2.1.330 hands a waking hook's text to the prompt hook inside its own wrapper,
    # so the marker is not the first line (seen in a real session): still not the person's reply.
    wrapped = (
        "<task-notification>\n<summary>Stop hook feedback</summary>\n</task-notification>\n"
        '<system-reminder>\nStop hook blocking error from command "Stop": '
        f"{text}\n\n</system-reminder>"
    )
    assert is_delivery(wrapped) and not is_delivery(wrapped.replace(text.splitlines()[-1], ""))
    run_hook(monkeypatch, capsys, database_url, "prompt", {"prompt": wrapped, "cwd": root})
    assert review_of(database_url, waiting)["status"] == "pending"
    assert turns(SESSION) == [("prompt", None), ("prompt", None)]

    # The person's own words, in the same chat, do settle it.
    run_hook(monkeypatch, capsys, database_url, "prompt", {"prompt": "Yes.", "cwd": root})
    assert review_of(database_url, waiting)["status"] == "answered"
    assert [source for source, _ in turns(SESSION)] == ["prompt", "prompt", "prompt"]


async def test_a_task_notification_from_claude_code_is_not_the_persons_reply(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    """Claude Code sends a message of its own when a background task finishes and when a hook,
    any hook, wakes the chat. It starts a turn; it settles no question and names no task."""
    from app.models.agent_session import AgentSessionEvent
    from app.models.task import Task
    from app.services.chat_delivery import is_delivery, is_task_notification

    w = await world(database_url, tmp_path)
    root, sub, notes = str(w["root"]), w["sub"], w["notes"]
    waiting = ask(database_url, w, notes, question="Ship in English only?")
    with database(database_url) as session:
        sub_id = session.query(Task.id).filter(Task.human_id == sub).scalar()

    def turns(chat: str) -> list[tuple[str, str | None]]:
        with database(database_url) as session:
            found = session.query(AgentSessionEvent).filter(
                AgentSessionEvent.session_id == chat, AgentSessionEvent.source == "prompt"
            )
            return [(e.source, e.task_id) for e in found.order_by(AgentSessionEvent.id)]

    # Each names the task, so a chat with none yet would take it for the task it works on.
    background = (
        "<task-notification>\n<task-id>bx4k29q1a</task-id>\n<status>completed</status>\n"
        f'<summary>Background command "pytest -k {sub}" completed (exit code 0)</summary>\n'
        "</task-notification>"
    )
    another_hooks_wake = (
        "<task-notification>\n<summary>Stop hook feedback</summary>\n</task-notification>\n"
        '<system-reminder>\nStop hook blocking error from command "Stop": the linter found '
        f"3 problems in {sub}. Fix them before you finish.\n</system-reminder>"
    )
    for message in (background, another_hooks_wake):
        assert is_task_notification(message) and not is_delivery(message)
        assert is_task_notification("\n  " + message)  # the hook strips it; so does the check
    # The person's words are not one, even when they mention one.
    for said in (
        "Yes.",
        f"Why did a <task-notification> about {sub} show up?",
        "",
        None,
        42,
    ):
        assert not is_task_notification(said), said

    # Control: the person's own message names the task for a chat that has none yet...
    run_hook(
        monkeypatch,
        capsys,
        database_url,
        "prompt",
        {"prompt": f"Let's get {sub} done.", "cwd": root, "session_id": OTHER},
    )
    assert turns(OTHER) == [("prompt", sub_id)]

    # ...a notification does not, and starts a turn all the same.
    for number, message in enumerate((background, another_hooks_wake), start=2):
        run_hook(
            monkeypatch,
            capsys,
            database_url,
            "prompt",
            {"prompt": message, "cwd": root, "session_id": OTHER},
        )
        assert turns(OTHER) == [("prompt", sub_id)] + [("prompt", None)] * (number - 1)

    # In the chat that asked, the question stays pending through both, each a turn of its own.
    for message in (background, another_hooks_wake):
        run_hook(monkeypatch, capsys, database_url, "prompt", {"prompt": message, "cwd": root})
        assert review_of(database_url, waiting)["status"] == "pending"
    assert turns(SESSION) == [("prompt", None), ("prompt", None)]

    # The person's own words, in the same chat, do settle it.
    run_hook(monkeypatch, capsys, database_url, "prompt", {"prompt": "Yes.", "cwd": root})
    assert review_of(database_url, waiting)["status"] == "answered"
    assert [source for source, _ in turns(SESSION)] == ["prompt"] * 3


async def test_the_message_reads_plainly_and_a_hook_can_tell_it_from_the_persons_words(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.services.chat_delivery import (
        DELIVERY_MARKER,
        delivery_ids,
        delivery_text,
        is_delivery,
        undelivered,
    )

    w = await world(database_url, tmp_path)
    sub, notes = w["sub"], w["notes"]
    first = ask(database_url, w, sub)
    second = hand_over(database_url, w, notes)
    long_comment = "Mind the zoom levels. " * 400
    decide(database_url, w, sub, "answer", "PNG")
    decide(database_url, w, notes, "reject", long_comment, file=b"a note")

    with database(database_url) as session:
        rows = undelivered(session, SESSION)
        assert [row.id for row in rows] == [first, second]
        text = delivery_text(session, rows)
    assert text.splitlines()[0] == DELIVERY_MARKER
    assert text.splitlines()[-1] == f"(Moah review ids: {first}, {second})"
    assert delivery_ids(text) == [first, second] and delivery_ids("Hello") == []
    assert "|" not in text and "```" not in text and "#" not in text  # no Markdown to render
    for private in (str(tmp_path), "/home", "/tmp", "\\"):
        assert private not in text
    assert "… (cut: the whole text is in Moah)" in text and len(text) < 4000
    assert is_delivery(text) and not is_delivery("Yes, WebP.") and not is_delivery(None)

    # The prompt hook never takes it for the person's reply.
    from app.services.chat_delivery import deliver

    with database(database_url) as session:
        assert deliver(session, SESSION, lambda _: None)  # handed over: nothing more to give
    # A question that any reply from the person would settle (it waits on a blocked task).
    other = ask(database_url, w, w["orchestrator"], question="Another one?")
    run_hook(monkeypatch, capsys, database_url, "prompt", {"prompt": text})
    assert review_of(database_url, other)["status"] == "pending"
    person_writes(database_url, "Yes, go on.")  # while the person's own words do settle it
    assert review_of(database_url, other)["status"] == "answered"


def test_the_waiters_own_module_needs_nothing_but_the_standard_library() -> None:
    """Imported by the entry points before anything else, for every Stop hook."""
    probe = (
        "import sys\n"
        "import app.services.chat_wait\n"
        "heavy = ('sqlalchemy', 'alembic', 'pydantic', 'fastapi')\n"
        "print(sorted(m for m in heavy if m in sys.modules))"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, cwd=BACKEND, timeout=60
    )
    assert done.stdout.strip() == "[]", done.stderr


async def test_a_stop_hook_without_a_question_loads_nothing_else(tmp_path: Path) -> None:
    """The Stop hook runs after every turn. One that ends on no question must cost a Python
    start: no SQLAlchemy, nothing waited for (and none of the 3 seconds ``--settle`` is for)."""
    database_path = tmp_path / "project-brain.db"
    async with app_client(f"sqlite:///{database_path}") as client:
        await sandbox(client, tmp_path)
    probe = (
        "import sys, runpy, time\n"
        "slept = []\n"
        "time.sleep = slept.append\n"  # a hook that waited would only note how long, here
        "sys.argv = ['project-moah-mcp', '--agent', %r, '--hook', 'stop'] + %r\n"
        "try:\n    runpy.run_module('app.mcp', run_name='__main__')\n"
        "except SystemExit as end:\n    assert end.code == 0, end.code\n"
        "print('sqlalchemy' in sys.modules, slept)"
    )
    env = {k: v for k, v in os.environ.items() if k != "PROJECT_BRAIN_DATABASE_URL"}
    for db in (tmp_path / "absent.db", database_path):
        env["PROJECT_BRAIN_DB_PATH"] = str(db)
        for who, flags in itertools.product(("claude", "codex"), ([], ["--settle"])):
            payload = json.dumps({"session_id": SESSION, "last_assistant_message": "All done."})
            began = time.monotonic()
            done = subprocess.run(
                [sys.executable, "-c", probe % (who, flags)],
                input=payload,
                capture_output=True,
                text=True,
                cwd=BACKEND,
                env=env,
                timeout=60,
            )
            assert done.stdout.strip() == "False []", (db.name, who, flags, done.stderr)
            # The sleeps above say nothing waited. The clock says it too, but a cold start of
            # Python on a busy Windows computer can take 3 seconds by itself.
            fast = sys.platform == "win32" or time.monotonic() - began < 3
            assert done.stderr == "" and fast, (who, flags)


# ---- the real commands ---------------------------------------------------------------------


def start_hook(database_url: str, *arguments: str, **fields: object) -> subprocess.Popen:
    """``python -m app.mcp --agent claude --hook ...``, as an agent starts it, with the hook's
    JSON on standard input. The input is a file that holds it, not a pipe that is closed after
    it: ``communicate()`` flushes a pipe it is given, and Python 3.12 does that on one already
    closed (3.13 does not)."""
    env = {k: v for k, v in os.environ.items() if k != "PROJECT_BRAIN_DB_PATH"}
    env["PROJECT_BRAIN_DATABASE_URL"] = database_url
    with tempfile.TemporaryFile() as given:
        given.write(json.dumps({"session_id": SESSION, **fields}).encode())
        given.seek(0)
        return subprocess.Popen(
            [sys.executable, "-m", "app.mcp", "--agent", "claude", *arguments],
            stdin=given,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=BACKEND,
            env=env,
        )


def wait_until(condition, hooks: list, what: str, seconds: float = 90) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        for hook in hooks:
            assert hook.poll() is None, (what, hook.args, hook.stderr.read())
        assert time.monotonic() < deadline, f"never happened: {what}"
        time.sleep(0.2)


def resident_megabytes(pid: int) -> float | None:
    """What the process holds in memory, on Linux (a waiter must stay small: it lives for hours)."""
    if not sys.platform.startswith("linux"):
        return None
    with open(f"/proc/{pid}/status") as status:
        return next(int(x.split()[1]) for x in status if x.startswith("VmRSS:")) / 1024


async def test_the_real_wait_hook_hands_an_answer_given_in_review_to_the_chat(
    database_url: str, tmp_path: Path
) -> None:
    w = await world(database_url, tmp_path)
    sub = w["sub"]
    asked = ask(database_url, w, sub)
    hook = start_hook(database_url, "--hook", "wait", hook_event_name="Stop")
    try:
        wait_until(lambda: waiting_rows(database_url), [hook], "the hook began to wait")
        waiting = resident_megabytes(hook.pid)
        print(f"waiting hook (--hook wait): {waiting} MB resident")
        assert waiting is None or waiting < 40
        decide(database_url, w, sub, "answer", "WebP")
        out, err = hook.communicate(timeout=60)
    finally:
        if hook.poll() is None:
            hook.kill()
            hook.wait(timeout=30)  # Windows keeps its files (the database) until it has ended
    assert hook.returncode == 2, (out, err)
    assert out == ""
    assert "Project Moah Review: the person decided in Review." in err
    assert "The person chose: WebP" in err and sub in err and asked in err
    assert review_of(database_url, asked)["delivered_at"] is not None
    database_path = database_url.removeprefix("sqlite:///")
    assert sqlite3.connect(database_path).execute("PRAGMA integrity_check").fetchone() == ("ok",)


async def test_the_two_real_stop_hooks_side_by_side_record_the_question_and_wake_the_chat(
    database_url: str, tmp_path: Path
) -> None:
    """The turn ends on a question. Claude Code starts both commands at once: the one that
    records (after its 3 seconds) and the waiter, which looks before the question is there."""
    from app.models.review import TaskReview

    w = await world(database_url, tmp_path)
    sub = w["sub"]
    await _chat_works_on(database_url, w, sub)
    recorder = start_hook(
        database_url, "--hook", "stop", "--settle", last_assistant_message=REAL_QUESTION
    )
    waiter = start_hook(database_url, "--hook", "wait", last_assistant_message=REAL_QUESTION)
    try:
        out, err = recorder.communicate(timeout=90)
        assert (recorder.returncode, out) == (0, ""), err
        with database(database_url) as session:
            [question] = session.query(TaskReview).all()
            assert (question.status, question.session_id) == ("pending", SESSION)
            asked = question.id
        wait_until(lambda: waiting_rows(database_url), [waiter], "the waiter saw the question")
        waiting = resident_megabytes(waiter.pid)
        print(f"waiting hook after the other recorded the question: {waiting} MB resident")
        assert waiting is None or waiting < 40  # recording happened in the other process
        decide(database_url, w, sub, "answer", "Both, in that order.")
        out, err = waiter.communicate(timeout=60)
    finally:
        for hook in (recorder, waiter):
            if hook.poll() is None:
                hook.kill()
                hook.wait(timeout=30)  # Windows keeps its files (the database) until it has ended
    assert waiter.returncode == 2, (out, err)
    assert out == "" and "The person answered: Both, in that order." in err and asked in err
    assert review_of(database_url, asked)["delivered_at"] is not None


async def test_a_question_asked_through_the_mcp_server_waits_for_the_answer_the_same_way(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    w = await world(database_url, tmp_path)
    sub = w["sub"]
    async with agent(database_url, "claude", "--session-id", SESSION) as mcp:
        await call(mcp, "brain_ask_person", task=sub, question=TILES, options=["PNG", "WebP"])
    clock = Clock()
    clock.at[1] = lambda: decide(database_url, w, sub, "answer", "PNG")

    code, text = wait(database_url, monkeypatch, capsys, clock)

    assert code == 2 and "The person chose: PNG" in text

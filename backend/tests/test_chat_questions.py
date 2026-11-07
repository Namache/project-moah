"""Questions agents ask in the chat reach Review through their Stop hook (chat_questions.py)."""

import io
import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.conftest import app_client
from tests.test_reviews import brief, submit_review, world

pytestmark = pytest.mark.anyio

SESSION = "0b5e8c1a-2f4d-4c6b-9a7e-3d1f5a9c8e20"  # made up

# What Claude Code (Sonnet 5.5) wrote in a real run on the Little Habits sandbox, before it had
# picked a task: it asked in the chat and never called brain_ask_person.
REAL_QUESTION = """Moah has no record of what the monthly summary should contain, and the code \
doesn't say either. Before I build anything, which numbers do you want on the stats screen?

My suggestion for a given month, from the same `YYYY-MM-DD` date strings:
1. **Days done**: the number of distinct days with the habit done (a day counts once, per DEC-003).
2. **Completion rate**: days done divided by days in that month.

I'd add it as a new `monthlySummary(dates, year, month)` in `src/streaks.js`, with tests.

Do you want that set, or something different? Also, should I leave the unfinished weekly \
streak (HAB-004) alone for now?"""


@contextmanager
def database(database_url: str):
    from app.db.session import make_engine, make_session_factory

    engine = make_engine(database_url)
    try:
        with make_session_factory(engine)() as session:
            yield session
    finally:
        engine.dispose()


def run_hook(monkeypatch, capsys, database_url: str, hook: str, payload: dict, agent="claude"):
    """Run the hook exactly as Claude Code or Codex does: JSON on standard input."""
    from app.mcp import cli

    monkeypatch.setattr(cli, "get_database_url", lambda: database_url)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": SESSION, **payload})))
    assert cli.main(["--agent", agent, "--hook", hook]) == 0
    printed = capsys.readouterr()
    # Claude Code adds a prompt hook's output to the person's message: it must print nothing.
    assert printed.out == "", printed.out
    assert f"Project Moah {hook} hook" not in printed.err, printed.err  # and nothing failed


def reviews_of(database_url: str, ref: str):
    from app.models.review import TaskReview
    from app.models.task import Task

    with database(database_url) as session:
        task = session.query(Task).filter(Task.human_id == ref).one()
        rows = session.query(TaskReview).filter(TaskReview.task_id == task.id)
        return task.status, [
            (r.kind, r.status, r.summary, r.details, r.options, r.comment, r.moved_to)
            for r in rows.order_by(TaskReview.round)
        ]


def test_question_in_finds_the_question_a_turn_ends_on() -> None:
    from app.services.chat_questions import question_in

    question, context, options = question_in(REAL_QUESTION)
    assert question.startswith("Do you want that set") and question.endswith("for now?")
    assert context.startswith("Moah has no record") and "monthlySummary" in context
    assert options == []
    # A heading before the questions, and a closing line after them, belong to the question.
    listed = "I looked at it.\n\nQuestions:\n\n1. Calendar month?\n2. Days so far?\n\nThen I start."
    assert (
        question_in(listed)[0]
        == "Questions:\n\n1. Calendar month?\n2. Days so far?\n\nThen I start."
    )
    # Short choices under the question become answer buttons in Review.
    choices = "Two ways.\n\nWhich do you prefer?\n- A JSON file\n- The database"
    assert question_in(choices) == (
        "Which do you prefer?\n- A JSON file\n- The database",
        "Two ways.",
        ["A JSON file", "The database"],
    )
    # Not questions for the person: courtesy, code, links, or no question at all.
    for text in (
        "Fixed, and the tests pass.\n\nAnything else?",
        "Done. Does that help?",
        "Here it is:\n\n```js\nconst a = b ? c : d; // why?\n```\n\nIt works.",
        "See https://example.com/?a=1 for details.",
        "All done. The tests pass.",
        "",
        None,
    ):
        assert question_in(text) is None, text


async def test_a_question_asked_in_the_chat_waits_in_review_until_answered_there(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.mcp.server import review_for_agent
    from app.models.agent_session import AgentSessionEvent
    from app.models.task import Task
    from app.services.agent_sessions import session_tasks

    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
    pid, root, legend = w["pid"], w["root"], w["other"]
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    from app.mcp import cli

    monkeypatch.setattr(cli, "get_database_url", lambda: database_url)
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(json.dumps({"session_id": SESSION, "source": "startup"}))
    )
    assert cli.main(["--brief"]) == 0
    capsys.readouterr()

    # The person asks for work the agent has not picked yet; their words name one To do task.
    run_hook(
        monkeypatch,
        capsys,
        database_url,
        "prompt",
        {"prompt": "Let's do the trail map legend.", "cwd": str(root)},
    )
    # The agent looks around and ends its turn on a question, in the chat.
    run_hook(monkeypatch, capsys, database_url, "stop", {"last_assistant_message": REAL_QUESTION})
    status, rounds = reviews_of(database_url, legend)
    assert status == "blocked"
    [(kind, state, question, context, _, _, _)] = rounds
    assert (kind, state) == ("question", "pending")
    assert question.startswith("Do you want that set") and context.startswith("Moah has no")
    # The same turn ending again (a retry, a second hook run) asks nothing new.
    run_hook(monkeypatch, capsys, database_url, "stop", {"last_assistant_message": REAL_QUESTION})
    assert len(reviews_of(database_url, legend)[1]) == 1

    async with app_client(database_url) as client:
        waiting = (await client.get("/api/reviews")).json()["waiting"]
        assert (waiting[0]["ref"], waiting[0]["question"], waiting[0]["agent"]) == (
            legend,
            True,
            "claude",
        )
        assert (await client.get("/api/reviews/pending")).json()["newest"][0]["question"]
    assert "1 question(s)" in brief(database_url, pid)

    # The person answers in the same chat: the question is settled, not left waiting in Review.
    run_hook(
        monkeypatch,
        capsys,
        database_url,
        "prompt",
        {
            "prompt": "Days done and completion rate. Leave the weekly streak alone.",
            "cwd": str(root),
        },
    )
    status, rounds = reviews_of(database_url, legend)
    assert status == "in_progress"
    assert rounds[0][1] == "answered" and rounds[0][6] == "chat"
    assert rounds[0][5] == "Days done and completion rate. Leave the weekly streak alone."
    text = brief(database_url, pid)
    assert "ANSWERED IN REVIEW" not in text and "question(s)" not in text  # the agent has it
    with database(database_url) as session:
        task = session.query(Task).filter(Task.human_id == legend).one()
        said = review_for_agent(session, task.id)["review"]
        assert said["status"].startswith("answered by the person in the chat")
        # Token use follows only what the MCP server recorded, never a task guessed from words.
        now = datetime.now(UTC)
        assert session_tasks(session, now - timedelta(hours=1), now + timedelta(hours=1)) == {}
        prompts = session.query(AgentSessionEvent).filter(AgentSessionEvent.source == "prompt")
        assert [bool(e.task_id) for e in prompts.order_by(AgentSessionEvent.id)] == [True, False]
    async with app_client(database_url) as client:
        reviewed = (await client.get("/api/reviews")).json()["reviewed"]
        assert (reviewed[0]["ref"], reviewed[0]["verdict"], reviewed[0]["moved_to"]) == (
            legend,
            "answered",
            "chat",
        )

    # A turn that ends on courtesy, or without a question, asks nothing.
    for message in ("Added the legend. Anything else?", "Added the legend; tests pass."):
        run_hook(monkeypatch, capsys, database_url, "stop", {"last_assistant_message": message})
    assert reviews_of(database_url, legend) == ("in_progress", rounds)


async def test_offers_after_a_hand_over_and_questions_the_tool_asked_are_left_alone(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.models.agent_session import AgentSessionEvent
    from app.models.task import Task
    from app.schemas.review import AskPerson
    from app.services.activity import acting_as
    from app.services.reviews import ReviewService

    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
    pid, badge = w["pid"], w["task"]
    with database(database_url) as session:
        task = session.query(Task).filter(Task.human_id == badge).one()
        session.add(  # the MCP server recorded the session's task, as it does for any call
            AgentSessionEvent(
                agent="claude", session_id=SESSION, project_id=pid, task_id=task.id, source="task"
            )
        )
        session.commit()
    run_hook(monkeypatch, capsys, database_url, "prompt", {"prompt": "Finish the badge."})

    # The agent asks with brain_ask_person and repeats the question in the chat, as told to.
    with database(database_url) as session, acting_as("claude", "claude"):
        ReviewService(session).ask(
            pid,
            badge,
            AskPerson(question="Show 0 or a red Full label?", options=["Show 0", "Full label"]),
            "claude",
        )
    run_hook(
        monkeypatch,
        capsys,
        database_url,
        "stop",
        {"last_assistant_message": "I asked in Review: should a full camp show 0 or a red label?"},
    )
    status, rounds = reviews_of(database_url, badge)
    assert status == "blocked"
    assert [(r[1], r[2], r[4]) for r in rounds] == [
        ("pending", "Show 0 or a red Full label?", ["Show 0", "Full label"])
    ]

    # Answered in Review, then handed over: the offer that ends the turn is not a question.
    async with app_client(database_url) as client:
        url = f"/api/projects/{pid}/tasks/{badge}/review/decision"
        answer = await client.post(url, json={"verdict": "answer", "comment": "Red Full label."})
        assert answer.status_code == 200, answer.text
    run_hook(monkeypatch, capsys, database_url, "prompt", {"prompt": "Go on."})
    submit_review(database_url, pid, badge)
    run_hook(
        monkeypatch,
        capsys,
        database_url,
        "stop",
        {"last_assistant_message": "Handed over.\n\nWant me to add a test for a full camp too?"},
    )
    status, rounds = reviews_of(database_url, badge)
    assert status == "review" and [r[:2] for r in rounds] == [
        ("question", "answered"),
        ("work", "pending"),
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"prompt": "Can you look at things?"},  # names no task
        {"prompt": "Let's do the trail map legend."},  # no project for this folder
    ],
)
async def test_without_a_task_nothing_is_caught(
    database_url: str, tmp_path: Path, monkeypatch, capsys, payload: dict
) -> None:
    from app.models.review import TaskReview

    async with app_client(database_url) as client:
        w = await world(client, tmp_path)
    cwd = str(w["root"]) if "things" in payload["prompt"] else str(tmp_path / "elsewhere")
    run_hook(monkeypatch, capsys, database_url, "prompt", {**payload, "cwd": cwd})
    run_hook(monkeypatch, capsys, database_url, "stop", {"last_assistant_message": REAL_QUESTION})
    with database(database_url) as session:
        assert session.query(TaskReview).count() == 0


def test_a_broken_hook_input_never_fails_the_agent(database_url: str, monkeypatch, capsys) -> None:
    from app.mcp import cli

    monkeypatch.setattr(cli, "get_database_url", lambda: database_url)
    for raw in ("not json", json.dumps({"session_id": "bad id with spaces", "prompt": "hi"})):
        monkeypatch.setattr("sys.stdin", io.StringIO(raw))
        assert cli.main(["--hook", "prompt"]) == 0
        printed = capsys.readouterr()
        assert printed.out == "" and "hook:" not in printed.err


def test_a_turn_without_a_question_ends_before_loading_the_database(tmp_path: Path) -> None:
    """The Stop hook runs after every turn: most end without a question and must stay cheap."""
    import subprocess
    import sys

    backend = Path(__file__).resolve().parents[1]
    probe = (
        "import sys, runpy\n"
        "sys.argv = ['project-moah-mcp', '--agent', 'claude', '--hook', 'stop']\n"
        "try:\n    runpy.run_module('app.mcp', run_name='__main__')\n"
        "except SystemExit as end:\n    assert end.code == 0, end.code\n"
        "print('sqlalchemy' in sys.modules)"
    )
    for message, loads in (("All done; the tests pass.", "False"), (REAL_QUESTION, "True")):
        payload = json.dumps({"session_id": SESSION, "last_assistant_message": message})
        done = subprocess.run(
            [sys.executable, "-c", probe],
            input=payload,
            capture_output=True,
            text=True,
            cwd=backend,
            env={"PROJECT_BRAIN_DB_PATH": str(tmp_path / "moah.db"), "PATH": "/usr/bin:/bin"},
            timeout=60,
        )
        assert done.stdout.strip() == loads, done.stderr

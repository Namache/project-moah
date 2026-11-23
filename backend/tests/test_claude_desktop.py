"""Review's button goes to the chat that asked (services/claude_desktop.py, agent_sessions.app_chat,
agent_prompts.chat_of).

The Claude desktop app keeps one JSON file per Claude Code chat in its own config folder. These
tests build that folder from made-up records in a temp directory (the real one is never read: see
conftest's no_real_claude_app), then check the search, the kept answer, and the five kinds of chat
the fix prompt reports."""

import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.services import claude_desktop
from app.services.agent_sessions import MISS_FOR
from app.services.claude_desktop import FOUND, NOT_FOUND, UNREADABLE, find, still_matches
from tests.conftest import app_client
from tests.test_chat_delivery import ask, decide, hand_over, world
from tests.test_chat_questions import SESSION, database
from tests.test_tool_hook import CODEX

pytestmark = pytest.mark.anyio

OTHER = "7c1e9b4a-3d52-4f80-a6c9-0e8d2b5f1a34"  # another chat, made up
LATER = "c4a8f2d1-6b97-4e03-95ad-1f7e3c8b2d60"  # the chat after a /clear, made up
LOCAL = "local_5d3b8f72-0c1a-4e96-b7d4-9a2e6c18f035"
LOCAL_2 = "local_a91c47e8-2b6d-4f03-8e15-c7d09b3a6f12"


def record(
    config: Path,
    local: str = LOCAL,
    cli: str | None = SESSION,
    last: str | None = None,
    archived: bool = False,
    age_days: float = 0,
    below: tuple[str, ...] = ("account-1", "org-1"),
    body: dict | None = None,
) -> Path:
    """A record the way the app keeps it: sessionId, the Claude Code ids, whether it is archived,
    and a good deal else (the real ones are hundreds of kilobytes)."""
    folder = config.joinpath(claude_desktop.FOLDER, *below)
    folder.mkdir(parents=True, exist_ok=True)
    data = {
        "sessionId": local,
        "cliSessionId": cli,
        "lastAssistantCliSessionId": last,
        "isArchived": archived,
        "title": "Trail map legend",
        "cwd": "/home/someone/trailhead",
        **(body or {}),
    }
    path = folder / f"{local}.json"
    path.write_text(json.dumps(data))
    moment = time.time() - age_days * 86400
    os.utime(path, (moment, moment))
    return path


@pytest.fixture
def config(tmp_path: Path) -> Path:
    folder = tmp_path / "app-config" / "Claude"
    (folder / claude_desktop.FOLDER).mkdir(parents=True)
    return folder


# ---- the search ----------------------------------------------------------------------------


def test_a_record_is_found_by_the_session_it_runs(config: Path) -> None:
    record(config, LOCAL, cli=SESSION)
    record(config, LOCAL_2, cli=OTHER)

    assert find(SESSION, [config]) == claude_desktop.Lookup(FOUND, LOCAL)
    assert find(OTHER, [config]) == claude_desktop.Lookup(FOUND, LOCAL_2)
    assert find(LATER, [config]) == claude_desktop.Lookup(NOT_FOUND)


def test_a_record_is_found_by_the_session_after_a_clear_too(config: Path) -> None:
    """The app keeps the id it started with and the id of the newest turn: both are the chat."""
    record(config, LOCAL, cli=SESSION, last=LATER)

    assert find(LATER, [config]).record == LOCAL
    assert find(SESSION, [config]).record == LOCAL


def test_an_archived_record_never_matches(config: Path) -> None:
    record(config, LOCAL, cli=SESSION, archived=True)
    assert find(SESSION, [config]) == claude_desktop.Lookup(NOT_FOUND)

    # A live record of the same session is still found, even when an archived one is newer.
    record(config, LOCAL_2, cli=SESSION, age_days=3)
    assert find(SESSION, [config]) == claude_desktop.Lookup(FOUND, LOCAL_2)


@pytest.mark.parametrize(
    "bad",
    [
        "../../etc/passwd",
        "local_",
        "local_" + "a" * 65,
        "local_with space",
        "session_5d3b8f72",
        "",
        5,
        None,
        ["local_5d3b8f72"],
    ],
)
def test_a_record_with_a_bad_id_is_ignored(config: Path, bad: object) -> None:
    record(config, LOCAL, cli=SESSION, body={"sessionId": bad})
    assert find(SESSION, [config]) == claude_desktop.Lookup(NOT_FOUND)


def test_only_the_two_claude_code_fields_count(config: Path) -> None:
    """The id is in the file's bytes, so the cheap check passes, but it is not the chat's."""
    record(config, LOCAL, cli=OTHER, body={"title": f"Notes about {SESSION}", "tags": [SESSION]})
    assert find(SESSION, [config]) == claude_desktop.Lookup(NOT_FOUND)


def test_a_record_that_is_not_json_is_skipped(config: Path) -> None:
    broken = record(config, LOCAL_2, cli=OTHER)
    broken.write_text(f'{{"cliSessionId": "{SESSION}", ')
    record(config, LOCAL, cli=SESSION, age_days=5)

    assert find(SESSION, [config]) == claude_desktop.Lookup(FOUND, LOCAL)


def test_old_records_are_not_read(config: Path) -> None:
    record(config, LOCAL, cli=SESSION, age_days=claude_desktop.MAX_AGE_DAYS + 1)
    assert find(SESSION, [config]) == claude_desktop.Lookup(NOT_FOUND)

    record(config, LOCAL, cli=SESSION, age_days=claude_desktop.MAX_AGE_DAYS - 1)
    assert find(SESSION, [config]) == claude_desktop.Lookup(FOUND, LOCAL)


def test_only_the_newest_files_are_read(config: Path) -> None:
    cap = claude_desktop.MAX_FILES
    for number in range(cap - 1):
        record(config, f"local_filler-{number:03}", cli=f"filler-{number}", age_days=number / 1000)
    # The 120th newest is the last that is read; the 121st is left out.
    record(config, LOCAL, cli=SESSION, age_days=1)
    record(config, LOCAL_2, cli=OTHER, age_days=2)

    assert find(SESSION, [config]).state == FOUND
    assert find(OTHER, [config]).state == NOT_FOUND


def test_it_stops_at_the_first_match_and_reads_the_newest_first(
    config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record(config, LOCAL, cli=SESSION, age_days=1)
    record(config, LOCAL_2, cli=SESSION, age_days=9)
    for number in range(5):
        record(config, f"local_other-{number}", cli=f"other-{number}", age_days=20 + number)
    reads: list[str] = []
    real = claude_desktop._read
    monkeypatch.setattr(claude_desktop, "_read", lambda path: reads.append(path.name) or real(path))

    assert find(SESSION, [config]).record == LOCAL
    assert reads == [f"{LOCAL}.json"]


@pytest.mark.parametrize("session_id", ["", "../x", "a b", "x" * 65, "ü"])
def test_a_session_id_that_cannot_be_one_reads_nothing(
    config: Path, monkeypatch: pytest.MonkeyPatch, session_id: str
) -> None:
    record(config, LOCAL, cli=SESSION)
    monkeypatch.setattr(os, "scandir", lambda *a, **k: pytest.fail("looked at the folder"))
    assert find(session_id, [config]) == claude_desktop.Lookup(NOT_FOUND)


def test_records_are_found_up_to_three_folders_down(config: Path) -> None:
    for depth in range(0, 5):
        below = tuple(f"level-{n}" for n in range(depth))
        record(config, f"local_depth-{depth}", cli=f"depth-{depth}", below=below)

    assert [find(f"depth-{n}", [config]).state for n in range(5)] == [
        FOUND,
        FOUND,
        FOUND,
        FOUND,
        NOT_FOUND,
    ]


def test_a_link_out_of_the_folder_is_not_followed(config: Path, tmp_path: Path) -> None:
    outside = tmp_path / "somewhere-else" / "Claude"
    record(outside, LOCAL, cli=SESSION, below=())
    try:
        (config / claude_desktop.FOLDER / "linked-folder").symlink_to(
            outside / claude_desktop.FOLDER, target_is_directory=True
        )
        (config / claude_desktop.FOLDER / f"{LOCAL}.json").symlink_to(
            outside / claude_desktop.FOLDER / f"{LOCAL}.json"
        )
    except OSError:
        pytest.skip("Windows needs Developer Mode or admin rights to create symlinks")

    assert find(SESSION, [config]) == claude_desktop.Lookup(NOT_FOUND)


def test_only_record_files_are_looked_at(config: Path) -> None:
    path = record(config, LOCAL, cli=SESSION)
    path.rename(path.with_name("notes.json"))
    path.with_name("local_x.json.bak").write_text(path.with_name("notes.json").read_text())

    assert find(SESSION, [config]) == claude_desktop.Lookup(NOT_FOUND)


# ---- found, not found, not readable --------------------------------------------------------


def test_an_app_with_no_code_chats_yet_is_not_found_not_unreadable(tmp_path: Path) -> None:
    app = tmp_path / "Claude"
    app.mkdir()
    assert find(SESSION, [app]) == claude_desktop.Lookup(NOT_FOUND)
    (app / claude_desktop.FOLDER).mkdir()
    assert find(SESSION, [app]) == claude_desktop.Lookup(NOT_FOUND)


def test_a_missing_folder_is_not_readable(tmp_path: Path) -> None:
    assert find(SESSION, [tmp_path / "no-such-app" / "Claude"]) == claude_desktop.Lookup(UNREADABLE)
    assert find(SESSION, []) == claude_desktop.Lookup(UNREADABLE)


def test_a_folder_that_may_not_be_read_is_not_readable(
    config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record(config, LOCAL, cli=SESSION)
    real = os.scandir

    def denied(path, *args, **kwargs):
        if Path(path) == config / claude_desktop.FOLDER:
            raise PermissionError(13, "Permission denied", str(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", denied)
    assert find(SESSION, [config]) == claude_desktop.Lookup(UNREADABLE)


def test_a_file_that_may_not_be_read_makes_a_miss_unreadable_but_not_a_match(
    config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locked = record(config, LOCAL_2, cli=OTHER, age_days=1)
    real = Path.read_bytes

    def read_bytes(self: Path) -> bytes:
        if self == locked:
            raise PermissionError(13, "Permission denied", str(self))
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    # What was not seen may have been the chat: not "not found".
    assert find(SESSION, [config]) == claude_desktop.Lookup(UNREADABLE)
    record(config, LOCAL, cli=SESSION, age_days=5)
    assert find(SESSION, [config]) == claude_desktop.Lookup(FOUND, LOCAL)


def test_the_flatpak_case_one_folder_is_missing_and_the_other_has_the_record(
    config: Path, tmp_path: Path
) -> None:
    record(config, LOCAL, cli=SESSION)
    missing = tmp_path / ".var" / "app" / "org.example.Moah" / "config" / "Claude"

    assert find(SESSION, [missing, config]).record == LOCAL
    assert find(OTHER, [missing, config]).state == NOT_FOUND
    assert find(SESSION, [missing]).state == UNREADABLE


def test_where_the_app_keeps_its_records(tmp_path: Path) -> None:
    home = tmp_path / "home"
    folders = claude_desktop.config_folders
    assert folders({}, "linux", home) == [home / ".config" / "Claude"]
    # Inside a Flatpak the config home points into ~/.var/app, so ~/.config is looked at as well.
    flatpak = {"XDG_CONFIG_HOME": str(home / ".var" / "app" / "org.example.Moah" / "config")}
    assert folders(flatpak, "linux", home) == [
        home / ".config" / "Claude",
        home / ".var" / "app" / "org.example.Moah" / "config" / "Claude",
    ]
    same = {"XDG_CONFIG_HOME": str(home / ".config")}
    assert folders(same, "linux", home) == [home / ".config" / "Claude"]
    assert folders({"XDG_CONFIG_HOME": "relative"}, "linux", home) == [home / ".config" / "Claude"]
    assert folders({}, "darwin", home) == [home / "Library" / "Application Support" / "Claude"]
    roaming = tmp_path / "Roaming"
    assert folders({"APPDATA": str(roaming)}, "win32", home) == [roaming / "Claude"]
    assert folders({}, "win32", home) == [home / "AppData" / "Roaming" / "Claude"]


# ---- looking at one record again -----------------------------------------------------------


def test_a_kept_record_is_checked_by_its_own_file(config: Path) -> None:
    path = record(config, LOCAL, cli=SESSION, age_days=200)  # old: the search would not look
    assert still_matches(LOCAL, SESSION, [config])

    record(config, LOCAL, cli=SESSION, archived=True)
    assert not still_matches(LOCAL, SESSION, [config])
    record(config, LOCAL, cli=OTHER)
    assert not still_matches(LOCAL, SESSION, [config])
    path.unlink()
    assert not still_matches(LOCAL, SESSION, [config])
    assert not still_matches("../LOCAL", SESSION, [config])
    assert not still_matches(LOCAL, "../x", [config])


# ---- the kept answer -----------------------------------------------------------------------


def kept(database_url: str, chat: str = SESSION) -> list[tuple[str, str | None]]:
    from app.models.agent_session import AgentSessionEvent

    with database(database_url) as session:
        rows = session.query(AgentSessionEvent).filter(AgentSessionEvent.session_id == chat)
        return [(r.source, r.app_session) for r in rows.order_by(AgentSessionEvent.id)]


async def test_a_found_record_is_kept_and_used_without_searching_again(
    database_url: str, config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.agent_sessions import app_chat

    async with app_client(database_url):
        pass
    record(config, LOCAL, cli=SESSION)
    with database(database_url) as session:
        assert app_chat(session, SESSION, [config]) == claude_desktop.Lookup(FOUND, LOCAL)
    assert kept(database_url) == [("app", LOCAL)]

    def searched(*args, **kwargs):
        raise AssertionError("searched the app's records again")

    monkeypatch.setattr(claude_desktop, "find", searched)
    with database(database_url) as session:
        assert app_chat(session, SESSION, [config]) == claude_desktop.Lookup(FOUND, LOCAL)
    assert kept(database_url) == [("app", LOCAL)]  # not written twice


@pytest.mark.parametrize("what", ["archived", "deleted", "other chat"])
async def test_a_kept_record_that_went_stale_is_dropped_and_searched_for_again(
    database_url: str, config: Path, what: str
) -> None:
    from app.services.agent_sessions import app_chat

    async with app_client(database_url):
        pass
    path = record(config, LOCAL, cli=SESSION)
    with database(database_url) as session:
        app_chat(session, SESSION, [config])
    assert kept(database_url) == [("app", LOCAL)]

    if what == "archived":
        record(config, LOCAL, cli=SESSION, archived=True)
    elif what == "deleted":
        path.unlink()
    else:
        record(config, LOCAL, cli=OTHER)
    with database(database_url) as session:
        assert app_chat(session, SESSION, [config]) == claude_desktop.Lookup(NOT_FOUND)
    assert kept(database_url) == []

    # The person starts the chat again in the app: found again under its new record, once the
    # miss is no longer remembered.
    record(config, LOCAL_2, cli=SESSION)
    later = datetime.now(UTC) + MISS_FOR + timedelta(seconds=1)
    with database(database_url) as session:
        assert app_chat(session, SESSION, [config], now=later) == claude_desktop.Lookup(
            FOUND, LOCAL_2
        )
    assert kept(database_url) == [("app", LOCAL_2)]


async def test_a_stale_record_is_replaced_by_the_one_that_now_runs_the_chat(
    database_url: str, config: Path
) -> None:
    from app.services.agent_sessions import app_chat

    async with app_client(database_url):
        pass
    record(config, LOCAL, cli=SESSION)
    with database(database_url) as session:
        app_chat(session, SESSION, [config])
    record(config, LOCAL, cli=SESSION, archived=True)
    record(config, LOCAL_2, cli=SESSION)

    with database(database_url) as session:
        assert app_chat(session, SESSION, [config]) == claude_desktop.Lookup(FOUND, LOCAL_2)
    assert kept(database_url) == [("app", LOCAL_2)]


async def test_nothing_is_kept_when_nothing_is_found(
    database_url: str, config: Path, tmp_path: Path
) -> None:
    from app.services.agent_sessions import app_chat

    async with app_client(database_url):
        pass
    with database(database_url) as session:
        assert app_chat(session, SESSION, [config]).state == NOT_FOUND
        assert app_chat(session, SESSION, [tmp_path / "none"]).state == UNREADABLE
    assert kept(database_url) == []


@pytest.mark.parametrize("what", ["not found", "unreadable"])
async def test_a_search_that_found_nothing_is_not_repeated_for_a_minute(
    database_url: str,
    config: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    what: str,
) -> None:
    """Review's box asks twice within seconds: a terminal chat must not read the files twice. A
    fake clock moves through the minute."""
    from app.services.agent_sessions import app_chat

    async with app_client(database_url):
        pass
    folders = [config] if what == "not found" else [tmp_path / "no-such-app" / "Claude"]
    state = NOT_FOUND if what == "not found" else UNREADABLE
    start = datetime.now(UTC)
    searches: list[str] = []
    real = claude_desktop.find
    monkeypatch.setattr(
        claude_desktop, "find", lambda *a, **k: searches.append(a[0]) or real(*a, **k)
    )

    def look(seconds: float, chat: str = SESSION) -> str:
        with database(database_url) as session:
            return app_chat(session, chat, folders, now=start + timedelta(seconds=seconds)).state

    assert look(0) == state and len(searches) == 1
    if what == "not found":
        record(config, LOCAL, cli=SESSION)  # the app takes the chat up just after
    assert look(4) == state and len(searches) == 1  # the box's second look: remembered
    assert look(59) == state and len(searches) == 1
    assert look(61) == (FOUND if what == "not found" else UNREADABLE)
    assert len(searches) == 2  # a minute later it looked again
    # Another chat is its own question, and a found record is kept in the database, not here.
    assert look(62, OTHER) == (NOT_FOUND if what == "not found" else UNREADABLE)
    assert len(searches) == 3


async def test_a_miss_is_remembered_per_chat_and_folder_and_forgotten_on_a_find(
    database_url: str, config: Path, tmp_path: Path
) -> None:
    from app.services import agent_sessions
    from app.services.agent_sessions import app_chat

    async with app_client(database_url):
        pass
    elsewhere = tmp_path / "other-app" / "Claude"
    (elsewhere / claude_desktop.FOLDER).mkdir(parents=True)
    now = datetime.now(UTC)
    with database(database_url) as session:
        assert app_chat(session, SESSION, [config], now=now).state == NOT_FOUND
        record(elsewhere, LOCAL, cli=SESSION)
        # Another folder is another question; the same chat in the first folder is remembered.
        assert app_chat(session, SESSION, [elsewhere], now=now).state == FOUND
        assert app_chat(session, SESSION, [config], now=now).state == NOT_FOUND
        agent_sessions.forget_app_misses()
        record(config, LOCAL_2, cli=SESSION)
        assert app_chat(session, SESSION, [config], now=now).state == FOUND


async def test_what_is_remembered_about_misses_stays_small(database_url: str, config: Path) -> None:
    from app.services import agent_sessions
    from app.services.agent_sessions import app_chat

    async with app_client(database_url):
        pass
    now = datetime.now(UTC)
    with database(database_url) as session:
        for number in range(agent_sessions._MISS_LIMIT + 20):
            app_chat(session, f"chat-{number}", [config], now=now)
    assert len(agent_sessions._misses) <= agent_sessions._MISS_LIMIT
    # Entries that ran out are dropped when the next one is written.
    with database(database_url) as session:
        app_chat(session, "chat-new", [config], now=now + MISS_FOR + timedelta(seconds=1))
    assert list(agent_sessions._misses) == [("chat-new", (str(config),))]


async def test_the_kept_record_is_not_a_task_a_project_a_claim_or_a_new_session(
    database_url: str, tmp_path: Path
) -> None:
    """Every reader of the session rows ignores source ``app``, even one that also names a task
    and a project (as the waiting note's test does)."""
    from datetime import timedelta

    from app.models.agent_session import AgentSessionEvent
    from app.models.task import Task
    from app.services import chat_questions
    from app.services.agent_sessions import (
        SESSION_ENV,
        SessionTracker,
        chat_working_on,
        record_start,
        session_tasks,
    )

    w = await world(database_url, tmp_path)
    async with app_client(database_url) as client:
        elsewhere = (await client.post("/api/projects", json={"name": "Elsewhere"})).json()["id"]
    now = datetime.now(UTC)
    with database(database_url) as session:
        project = w["pid"]
        task = session.query(Task).filter(Task.human_id == w["sub"]).one()
        env = {"CLAUDE_PID": "4242"}
        record_start(session, "claude", {"session_id": SESSION, "source": "startup"}, project, env)
        session.add_all(
            [
                AgentSessionEvent(
                    agent="claude",
                    session_id=OTHER,
                    project_id=elsewhere,
                    task_id=task.id,
                    source="app",
                    agent_pid="4242",
                    app_session=LOCAL,
                    created_at=now + timedelta(seconds=5),
                ),
                AgentSessionEvent(
                    agent="claude",
                    session_id=SESSION,
                    project_id=elsewhere,
                    task_id=task.id,
                    source="app",
                    app_session=LOCAL_2,
                    created_at=now + timedelta(seconds=6),
                ),
            ]
        )
        session.commit()

        # No task, no project, no token use came from it.
        assert chat_questions.session_task(session, "claude", SESSION) is None
        assert chat_questions.session_task(session, "claude", OTHER) is None
        assert chat_questions._project(session, "claude", OTHER, None) is None
        assert chat_questions._project(session, "claude", SESSION, None).id == project
        assert chat_working_on(session, task.id, now + timedelta(seconds=10)) is None
        assert session_tasks(session, now - timedelta(hours=1), now + timedelta(hours=1)) == {}
        # A server that follows /clear stays with its own chat: the row is not a new session.
        tracker = SessionTracker("claude", {SESSION_ENV: SESSION})
        assert tracker.refresh(session) is False and tracker.current == SESSION
        # And one with no session id adopts the chat the hook saw start, not an app row's.
        guess = SessionTracker("claude", {})
        assert guess.adopt(session, project, datetime.now(UTC) + timedelta(seconds=20))
        assert guess.current == SESSION


# ---- what the fix prompt says about the chat -----------------------------------------------


def chat_for(database_url: str, ref: str, **changes: object) -> None:
    """Make the latest round of the task as the agent's hook would have left it."""
    from app.models.review import TaskReview
    from app.models.task import Task

    with database(database_url) as session:
        task = session.query(Task).filter(Task.human_id == ref).one()
        latest = (
            session.query(TaskReview)
            .filter(TaskReview.task_id == task.id)
            .order_by(TaskReview.round.desc())
            .first()
        )
        for name, value in changes.items():
            setattr(latest, name, value)
        session.commit()


async def fix_prompt(database_url: str, w: dict, ref: str, agent: str = "claude") -> dict:
    async with app_client(database_url) as client:
        found = await client.get(
            f"/api/projects/{w['pid']}/tasks/{ref}/review/fix-prompt", params={"agent": agent}
        )
        assert found.status_code == 200, found.text
        return found.json()


async def asked_and_answered(database_url: str, tmp_path: Path, chat: str | None = SESSION):
    w = await world(database_url, tmp_path)
    ask(database_url, w, w["sub"], chat=chat)
    decide(database_url, w, w["sub"], "answer", "WebP")
    return w


async def test_a_chat_the_desktop_app_knows_opens_in_the_app(
    database_url: str, tmp_path: Path, config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(claude_desktop, "config_folders", lambda *a, **k: [config])
    record(config, LOCAL, cli=SESSION)
    w = await asked_and_answered(database_url, tmp_path)

    got = await fix_prompt(database_url, w, w["sub"])

    assert got["chat"] == {
        "kind": "desktop",
        "agent": "claude",
        "url": f"claude://code/continue?session={LOCAL}",
        "delivered": False,
        "resume": None,
    }
    # What the new-chat button needs is where it was.
    assert (got["agent"], got["task"]) == ("claude", w["sub"])
    assert got["folder"].endswith("harbor-lights")
    assert got["url"].startswith("claude://code/new?q=") and "WebP" in got["prompt"]
    assert kept(database_url) == [("app", LOCAL)]


async def test_a_chat_the_app_does_not_know_is_a_terminal_chat(
    database_url: str, tmp_path: Path, config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(claude_desktop, "config_folders", lambda *a, **k: [config])
    record(config, LOCAL_2, cli=OTHER)  # some other chat, not this one
    w = await asked_and_answered(database_url, tmp_path)

    chat = (await fix_prompt(database_url, w, w["sub"]))["chat"]

    assert chat == {
        "kind": "terminal",
        "agent": "claude",
        "url": None,
        "delivered": False,
        "resume": None,
    }


async def test_a_chat_whose_app_records_cannot_be_read_is_elsewhere(
    database_url: str, tmp_path: Path
) -> None:
    w = await asked_and_answered(database_url, tmp_path)  # the app is "not installed" (conftest)

    chat = (await fix_prompt(database_url, w, w["sub"]))["chat"]

    assert chat["kind"] == "elsewhere" and chat["url"] is None and chat["resume"] is None


async def test_a_codex_chat_has_its_thread_link_and_a_resume_command(
    database_url: str, tmp_path: Path
) -> None:
    w = await asked_and_answered(database_url, tmp_path, chat=CODEX)
    chat_for(database_url, w["sub"], agent="codex")

    got = await fix_prompt(database_url, w, w["sub"], agent="codex")

    assert got["chat"] == {
        "kind": "codex",
        "agent": "codex",
        "url": f"codex://threads/{CODEX}",
        "delivered": False,
        "resume": f"codex resume {CODEX}",
    }
    assert got["url"].startswith("codex://new?prompt=")  # the new-chat link is still there


@pytest.mark.parametrize("chat", ["not-a-uuid", "019a7c2e-5b1f-7c3a-8e4d-2f6b9a1c0d37; rm -rf ~"])
async def test_a_codex_chat_id_that_is_not_a_uuid_is_not_linked(
    database_url: str, tmp_path: Path, chat: str
) -> None:
    w = await asked_and_answered(database_url, tmp_path, chat=None)
    chat_for(database_url, w["sub"], agent="codex", session_id=chat)

    got = (await fix_prompt(database_url, w, w["sub"], agent="codex"))["chat"]

    assert got["kind"] == "unknown" and got["url"] is None and got["resume"] is None


async def test_a_question_that_remembers_no_chat_is_unknown(
    database_url: str, tmp_path: Path
) -> None:
    w = await asked_and_answered(database_url, tmp_path, chat=None)

    chat = (await fix_prompt(database_url, w, w["sub"]))["chat"]

    assert chat == {
        "kind": "unknown",
        "agent": "claude",
        "url": None,
        "delivered": False,
        "resume": None,
    }


@pytest.mark.parametrize("name", ["human", "Some other agent", ""])
async def test_an_agent_that_is_not_claude_or_codex_is_unknown(
    database_url: str, tmp_path: Path, name: str
) -> None:
    w = await asked_and_answered(database_url, tmp_path)
    chat_for(database_url, w["sub"], agent=name)

    chat = (await fix_prompt(database_url, w, w["sub"]))["chat"]

    assert chat["kind"] == "unknown" and chat["agent"] is None and chat["url"] is None


@pytest.mark.parametrize("kind", ["desktop", "terminal", "elsewhere", "codex", "unknown"])
async def test_the_chat_says_whether_it_already_took_the_answer(
    database_url: str, tmp_path: Path, config: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    if kind != "elsewhere":
        monkeypatch.setattr(claude_desktop, "config_folders", lambda *a, **k: [config])
    if kind == "desktop":
        record(config, LOCAL, cli=SESSION)
    chat = {"unknown": None, "codex": CODEX}.get(kind, SESSION)
    agent = "codex" if kind == "codex" else "claude"
    w = await asked_and_answered(database_url, tmp_path, chat=chat)
    chat_for(database_url, w["sub"], agent=agent)

    before = await fix_prompt(database_url, w, w["sub"], agent)
    chat_for(database_url, w["sub"], delivered_at=datetime.now(UTC))
    after = await fix_prompt(database_url, w, w["sub"], agent)

    assert (before["chat"]["kind"], before["chat"]["delivered"]) == (kind, False)
    assert (after["chat"]["kind"], after["chat"]["delivered"]) == (kind, True)


async def test_a_send_back_says_where_the_chat_is_too(
    database_url: str, tmp_path: Path, config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(claude_desktop, "config_folders", lambda *a, **k: [config])
    record(config, LOCAL, cli=SESSION)
    w = await world(database_url, tmp_path)
    hand_over(database_url, w, w["sub"], chat=SESSION)
    decide(database_url, w, w["sub"], "reject", "The tile names are wrong at zoom 3.")

    got = await fix_prompt(database_url, w, w["sub"])

    assert "The tile names are wrong at zoom 3." in got["prompt"]
    assert got["chat"]["kind"] == "desktop"
    assert got["chat"]["url"] == f"claude://code/continue?session={LOCAL}"


async def test_a_task_that_was_not_sent_back_has_no_prompt_and_no_search(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = await world(database_url, tmp_path)
    ask(database_url, w, w["sub"], chat=SESSION)  # still waiting: nothing was decided
    monkeypatch.setattr(claude_desktop, "find", lambda *a, **k: pytest.fail("searched"))

    async with app_client(database_url) as client:
        got = await client.get(
            f"/api/projects/{w['pid']}/tasks/{w['sub']}/review/fix-prompt?agent=claude"
        )
    assert got.status_code == 409

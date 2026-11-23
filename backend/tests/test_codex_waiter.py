"""What the person decides in Review reaches a Codex session (codex_waiter.py, chat_wait.py).

Codex's hooks block, so its Stop hook records and starts ONE detached waiter, which runs
``codex queue`` when the person decides (or, in a Flatpak, prints it for the hook line's own shell
to queue). The world is test_tool_hook's harbor-map project, and the Codex chat is a made-up
thread. The waiter runs on a fake clock with fake ``codex`` programs that log what they were
given; the shell line of the Flatpak and the detached start run as real processes, and one test
runs the real Codex binary (set MOAH_TEST_CODEX, or have ``codex`` on PATH) against a throwaway
CODEX_HOME."""

import io
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile
from datetime import timedelta
from pathlib import Path

import pytest

from tests.test_chat_delivery import (
    BACKEND,
    HAND_OVER,
    Clock,
    decide,
    hand_over,
    logged_errors,
    review_of,
    wait_until,
    waiting_rows,
    world,
)
from tests.test_chat_questions import REAL_QUESTION, database
from tests.test_tool_hook import CODEX, OTHER, TILES

pytestmark = pytest.mark.anyio

OPTIONS = ["PNG", "WebP"]
NASTY = "Use \"WebP\" & 'PNG'; $HOME `whoami` $(id) \\n and\nsecond line,  two spaces \\"
MOAH_TOOL = [sys.executable, "-m", "app.mcp"]
WINDOWS = sys.platform == "win32"


# ---- the world, and a Codex that logs --------------------------------------------------------


def ask(database_url: str, w: dict, ref: str, question: str = TILES, chat: str = CODEX) -> str:
    """Codex asks about a task through Moah. Returns the review's id."""
    from app.schemas.review import AskPerson
    from app.services.activity import acting_as
    from app.services.reviews import ReviewService

    payload = AskPerson(question=question, options=OPTIONS)
    with database(database_url) as session, acting_as("codex", "codex"):
        return ReviewService(session).ask(w["pid"], ref, payload, "codex", session_id=chat).id


def chat_writes(database_url: str, text: str, chat: str = CODEX, agent: str = "codex") -> None:
    """The person writes in the chat: what the prompt hook does with the message."""
    from app.services.chat_questions import record_prompt

    with database(database_url) as session:
        record_prompt(session, agent, {"session_id": chat, "prompt": text})


def fake_source(log: Path, code: int = 0, pause: float = 0.0) -> str:
    """The Python of a fake ``codex``: it writes down what it was started with (one JSON line in
    ``log``: the arguments and its process id), says "queue said no" on standard error and ends
    with ``code``."""
    return (
        "import json, os, sys, time\n"
        f"with open({str(log)!r}, 'a') as log:\n"
        "    log.write(json.dumps({'argv': sys.argv[1:], 'pid': os.getpid()}) + '\\n')\n"
        f"time.sleep({pause})\n"
        "sys.stderr.write('queue said no\\n')\n"
        f"sys.exit({code})\n"
    )


def pips_launcher() -> bytes:
    """The program pip starts its own commands with (``pip.exe``): it runs ``python.exe`` on
    itself, with the arguments it was given. Windows runs nothing from a ``#!`` line, so a fake
    ``codex.exe`` is made of it; a test that needs one is skipped where pip does not have it."""
    try:
        from pip._vendor import distlib
    except ImportError:
        pytest.skip("pip is not installed here: no launcher to make a fake codex.exe from")
    name = "t64-arm.exe" if platform.machine().lower() in ("arm64", "aarch64") else "t64.exe"
    launcher = Path(distlib.__file__).with_name(name)
    if not launcher.is_file():
        pytest.skip(f"pip has no {name}: no launcher to make a fake codex.exe from")
    return launcher.read_bytes()


def windows_program(source: str, launcher: bytes) -> bytes:
    """What the launcher runs, laid out as distlib lays out a command: the launcher, a ``#!``
    line naming the interpreter (in quotes only when its path has a space), and a zip whose
    ``__main__.py`` is ``source``."""
    interpreter = f'"{sys.executable}"' if " " in sys.executable else sys.executable
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("__main__.py", source)
    return launcher + f"#!{interpreter}\n".encode() + archive.getvalue()


def write_program(path: Path, source: str) -> Path:
    """Make ``path`` a program that runs ``source`` when it is started. A ``#!`` line does it,
    except on Windows, where a ``.exe`` is built (``windows_program``) and anything else (the
    ``codex.cmd`` of npm) stays a script: one that must never be run."""
    if WINDOWS and path.suffix.lower() == ".exe":
        path.write_bytes(windows_program(source, pips_launcher()))
        return path
    path.write_text(f"#!{sys.executable}\n{source}")
    path.chmod(0o755)
    return path


def fake_codex(folder: Path, name: str = "codex", code: int = 0, pause: float = 0.0) -> Path:
    """A ``codex`` that logs what it was started with (``fake_source``) in ``codex.log`` beside
    it. Returns its path: on Windows a ``<name>.exe``, the only kind of file that is run there."""
    folder.mkdir(parents=True, exist_ok=True)
    if WINDOWS and not name.lower().endswith((".exe", ".cmd", ".bat")):
        name += ".exe"
    return write_program(folder / name, fake_source(folder / "codex.log", code, pause))


def codex_calls(folder: Path) -> list[dict]:
    log = folder / "codex.log"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def environment(database_url: str, *folders: Path, **more: str) -> dict:
    """What a hook runs in: the database, and ``codex`` found in ``folders`` before anywhere."""
    env = {k: v for k, v in os.environ.items() if k != "PROJECT_BRAIN_DB_PATH"}
    env["PROJECT_BRAIN_DATABASE_URL"] = database_url
    env["PATH"] = os.pathsep.join([*map(str, folders), env.get("PATH", "")])
    env["PYTHONPATH"] = str(BACKEND)  # for a process that starts anywhere but here
    env.update(more)
    return env


def answer_text(sub: str, asked: str, said: str, chose: bool = False) -> str:
    """The message of one answered question, as chat_delivery.delivery_text words it."""
    return (
        "Project Moah Review: the person decided in Review.\n\n"
        f'{sub} "Choose the tile format for map export"\n'
        f"You asked: {TILES}\n"
        f"The person {'chose' if chose else 'answered'}: {said}\n"
        "Next: carry on with the task using this answer. Do not ask it again: it is already "
        f"recorded in Moah.\n\n(Moah review ids: {asked})"
    )


def hook(
    database_url: str,
    monkeypatch,
    capsys,
    argv: list[str],
    env: dict,
    clock: Clock | None = None,
    stdin: str = "",
    **options,
) -> tuple[int, str, str]:
    """Run a hook command as its entry point does (chat_wait.before_loading, then the command
    itself) with ``stdin`` as its input. Returns the exit code and what it printed."""
    from app.mcp import cli
    from app.services import chat_wait

    capsys.readouterr()  # what building the world printed
    monkeypatch.setenv("PROJECT_BRAIN_DATABASE_URL", database_url)
    monkeypatch.delenv("PROJECT_BRAIN_DB_PATH", raising=False)
    monkeypatch.setattr(cli, "get_database_url", lambda: database_url)
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    if clock is not None:
        options = {"clock": clock, "sleep": clock.sleep, **options}
    run = chat_wait.Run(environ=env, **options)
    code = chat_wait.before_loading(argv, run)
    if code is None:
        code = cli.main(argv)
    printed = capsys.readouterr()
    return code, printed.out, printed.err


WAIT = ["--agent", "codex", "--hook", "wait", "--session-id", CODEX]


def codex_wait(database_url, monkeypatch, capsys, clock, *folders, flags=(), **options):
    """The detached waiter of the Codex chat, on the fake clock, with ``folders`` on its PATH."""
    env = options.pop("env", None) or environment(database_url, *folders)
    return hook(database_url, monkeypatch, capsys, [*WAIT, *flags], env, clock, **options)


async def two_answers(database_url: str, tmp_path: Path):
    """The chat has asked about two tasks and the person answers both (long answers)."""
    w = await world(database_url, tmp_path)
    first = ask(database_url, w, w["sub"])
    second = ask(database_url, w, w["notes"], question="Ship the notes in English only?")
    return w, first, second


# ---- starting the waiter -----------------------------------------------------------------


class Started:
    """What ``subprocess.Popen`` was asked for, in place of starting anything."""

    def __init__(self, monkeypatch, refuse: int = 0) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self.refuse = refuse  # the first this many tries fail, as CreateProcess can
        monkeypatch.setattr(subprocess, "Popen", self)

    def __call__(self, command, **options):
        if self.refuse:
            self.refuse -= 1
            raise PermissionError("not allowed to leave the job")
        self.calls.append((command, options))


def stop_argv(*flags: str, agent: str = "codex") -> list[str]:
    return ["--agent", agent, "--hook", "stop", *flags]


def stop(database_url, monkeypatch, capsys, message="All done.", agent="codex", **options):
    """Codex's Stop hook for the made-up chat, ending its turn on ``message``."""
    payload = json.dumps({"session_id": CODEX, "last_assistant_message": message})
    env = options.pop("env", None) or environment(database_url)
    return hook(
        database_url, monkeypatch, capsys, stop_argv(agent=agent), env, stdin=payload, **options
    )


@pytest.fixture
def source_command(monkeypatch) -> list[str]:
    """How a source install's Codex started this hook: ``python -m app.mcp ...``."""
    argv = ["/venv/bin/python3.13", "-m", "app.mcp", *stop_argv()]
    monkeypatch.setattr(sys, "orig_argv", argv)
    return MOAH_TOOL


async def test_the_stop_hook_of_a_chat_with_a_question_open_starts_one_detached_waiter(
    database_url: str, tmp_path: Path, monkeypatch, capsys, source_command
) -> None:
    w = await world(database_url, tmp_path)
    ask(database_url, w, w["sub"])
    started = Started(monkeypatch)

    # The POSIX way to start it, as on any system but Windows (the next test but two is Windows').
    code, out, err = stop(database_url, monkeypatch, capsys, windows=False)

    assert (code, out) == (0, "")  # Codex wants nothing, or JSON, on standard output
    [(command, options)] = started.calls
    assert command == [*source_command, *WAIT]
    assert options["start_new_session"] is True and options["close_fds"] is True
    for stream in ("stdin", "stdout", "stderr"):
        assert options[stream] == subprocess.DEVNULL  # none of Codex's pipes
    assert "cwd" not in options and "creationflags" not in options
    assert options["env"]["PROJECT_BRAIN_DATABASE_URL"] == database_url


async def test_a_turn_that_ends_on_a_question_is_recorded_and_then_gets_its_waiter(
    database_url: str, tmp_path: Path, monkeypatch, capsys, source_command
) -> None:
    from app.models.review import TaskReview

    w = await world(database_url, tmp_path)
    _chat_works_on_codex(database_url, w, w["sub"])
    started = Started(monkeypatch)

    code, out, err = stop(database_url, monkeypatch, capsys, message=REAL_QUESTION)

    assert (code, out) == (0, "")
    with database(database_url) as session:
        [question] = session.query(TaskReview).all()
        assert (question.status, question.session_id) == ("pending", CODEX)  # recorded first
    assert [command for command, _ in started.calls] == [[*source_command, *WAIT]]


def _chat_works_on_codex(database_url: str, w: dict, ref: str) -> None:
    from datetime import UTC, datetime

    from app.models.agent_session import AgentSessionEvent
    from app.models.task import Task

    with database(database_url) as session:
        task_id = session.query(Task.id).filter(Task.human_id == ref).scalar()
        session.add(
            AgentSessionEvent(
                agent="codex",
                session_id=CODEX,
                project_id=w["pid"],
                task_id=task_id,
                source="task",
                created_at=datetime.now(UTC),
            )
        )
        session.commit()


async def test_a_decision_waiting_for_the_chat_starts_a_waiter_too(
    database_url: str, tmp_path: Path, monkeypatch, capsys, source_command
) -> None:
    """The person answered while the turn ran: nothing is open any more, but the answer is
    still to be handed over."""
    w = await world(database_url, tmp_path)
    ask(database_url, w, w["sub"])
    decide(database_url, w, w["sub"], "answer", "WebP")
    started = Started(monkeypatch)

    assert stop(database_url, monkeypatch, capsys)[0] == 0

    assert len(started.calls) == 1


async def test_no_waiter_starts_when_there_is_nothing_to_wait_for(
    database_url: str, tmp_path: Path, monkeypatch, capsys, source_command
) -> None:
    w = await world(database_url, tmp_path)
    ask(database_url, w, w["sub"], chat=OTHER)  # another chat's question
    ask(database_url, w, w["notes"])
    decide(database_url, w, w["notes"], "answer", "No.")
    from app.services.chat_delivery import deliver

    with database(database_url) as session:
        assert deliver(session, CODEX, lambda _: None)  # and the answer was handed over already
    started = Started(monkeypatch)

    assert stop(database_url, monkeypatch, capsys) == (0, "", "")
    assert started.calls == []

    absent = {"PROJECT_BRAIN_DATABASE_URL": f"sqlite:///{tmp_path}/nothing-here.db"}
    assert stop(database_url, monkeypatch, capsys, env={**os.environ, **absent})[0] == 0
    assert started.calls == []  # and a computer without a database has nothing at all


async def test_only_codex_and_only_a_valid_chat_get_a_detached_waiter(
    database_url: str, tmp_path: Path, monkeypatch, capsys, source_command
) -> None:
    w = await world(database_url, tmp_path)
    ask(database_url, w, w["sub"])
    started = Started(monkeypatch)

    assert stop(database_url, monkeypatch, capsys, agent="claude")[0] == 0
    # Claude Code's own hook line starts the waiter there, with a turn that ended on a question too
    assert stop(database_url, monkeypatch, capsys, REAL_QUESTION, agent="claude")[0] == 0
    assert started.calls == []

    code, out, err = hook(
        database_url,
        monkeypatch,
        capsys,
        stop_argv(),
        environment(database_url),
        stdin=json.dumps({"session_id": "../../etc", "last_assistant_message": "Done."}),
    )
    assert (code, out) == (0, "") and started.calls == []


async def test_inside_a_sandbox_the_stop_hook_only_records(
    database_url: str, tmp_path: Path, monkeypatch, capsys, source_command
) -> None:
    from app.services import codex_waiter

    w = await world(database_url, tmp_path)
    ask(database_url, w, w["sub"])
    flatpak_info = tmp_path / "flatpak-info"
    flatpak_info.write_text("[Application]\n")
    monkeypatch.setattr(codex_waiter, "FLATPAK_INFO", flatpak_info)
    started = Started(monkeypatch)

    assert stop(database_url, monkeypatch, capsys)[:2] == (0, "")
    assert started.calls == []  # the hook line's shell does it there
    assert codex_waiter.sandboxed() is True
    flatpak_info.unlink()
    assert codex_waiter.sandboxed() is False


async def test_on_windows_the_waiter_leaves_the_agents_job_and_the_console(
    database_url: str, tmp_path: Path, monkeypatch, capsys, source_command
) -> None:
    from app.services import codex_waiter as cw

    w = await world(database_url, tmp_path)
    ask(database_url, w, w["sub"])
    flags = cw.DETACHED_PROCESS | cw.CREATE_NEW_PROCESS_GROUP | cw.CREATE_NO_WINDOW
    assert (cw.DETACHED_PROCESS, cw.CREATE_NEW_PROCESS_GROUP) == (0x8, 0x200)
    assert (cw.CREATE_NO_WINDOW, cw.CREATE_BREAKAWAY_FROM_JOB) == (0x08000000, 0x01000000)

    started = Started(monkeypatch)
    assert stop(database_url, monkeypatch, capsys, windows=True)[0] == 0
    [(command, options)] = started.calls
    assert options["creationflags"] == flags | cw.CREATE_BREAKAWAY_FROM_JOB  # first try
    assert "start_new_session" not in options
    assert options["cwd"] == os.path.expanduser("~")  # not the project's folder, which it locks
    assert command == [*source_command, *WAIT]

    # A job that does not allow leaving it: CreateProcess refuses, and the second try goes on.
    started = Started(monkeypatch, refuse=1)
    assert stop(database_url, monkeypatch, capsys, windows=True)[0] == 0
    [(_, options)] = started.calls
    assert options["creationflags"] == flags

    # Both refused: nothing started, nothing printed, the hook still ends with 0 and says why.
    started = Started(monkeypatch, refuse=2)
    assert stop(database_url, monkeypatch, capsys, windows=True) == (0, "", "")
    assert started.calls == []
    assert any("not started" in entry["message"] for entry in logged_errors(database_url))


def test_the_launcher_is_whatever_started_the_hook_up_to_its_own_options() -> None:
    from app.services.codex_waiter import launcher, waiter_command

    tail = ["--agent", "codex", "--hook", "stop"]
    py = "/opt/venv/bin/python"
    # A source install, a frozen executable, the desktop service's --mcp form, a bare program
    # name, the options of the interpreter, and the --agent=codex spelling.
    assert launcher([py, "-m", "app.mcp", *tail], py) == [py, "-m", "app.mcp"]
    exe = r"C:\Program Files\Project Moah\resources\bin\project-brain-backend.exe"
    assert launcher([exe, "--mcp", *tail], exe) == [exe, "--mcp"]
    assert launcher(["project-brain-backend", "--mcp", *tail], "/o/pbb") == ["/o/pbb", "--mcp"]
    assert launcher(
        ["python", "-X", "utf8", "-m", "app.mcp", "--agent=codex", "--hook=stop"], py
    ) == [
        py,
        "-X",
        "utf8",
        "-m",
        "app.mcp",
    ]
    assert launcher([py, "-m", "app.mcp"], py) == []  # no way to tell what to start
    assert launcher([], py) == []
    assert waiter_command(CODEX, [py, "-m", "app.mcp", *tail], py) == [
        py,
        "-m",
        "app.mcp",
        "--agent",
        "codex",
        "--hook",
        "wait",
        "--session-id",
        CODEX,
    ]
    # An interpreter that does not keep its command line: how an install starts its MCP server.
    assert waiter_command(CODEX, [], py, frozen=False)[:3] == [py, "-m", "app.mcp"]
    assert waiter_command(CODEX, [], exe, frozen=True)[:2] == [exe, "--mcp"]
    assert waiter_command(CODEX, ["x"], exe, frozen=True)[-5:] == WAIT[-5:]


def test_a_frozen_executables_markers_do_not_follow_it_into_the_waiter() -> None:
    from app.services.codex_waiter import child_environment

    plain = {"PATH": "/usr/bin", "LD_LIBRARY_PATH": "/mine", "_PYI_APPLICATION_HOME_DIR": "x"}
    assert child_environment(plain, False) == plain  # a source install passes it all on
    frozen = {
        **plain,
        "LD_LIBRARY_PATH": "/opt/Project Moah/_internal",
        "LD_LIBRARY_PATH_ORIG": "/original",
        "_MEIPASS2": "/tmp/_MEI1",
        "ELECTRON_RUN_AS_NODE": "1",
    }
    assert child_environment(frozen, True) == {
        "PATH": "/usr/bin",
        "LD_LIBRARY_PATH": "/original",
        "PYINSTALLER_RESET_ENVIRONMENT": "1",
    }
    unset = {"PATH": "/usr/bin", "LD_LIBRARY_PATH": "/opt/Project Moah/_internal"}
    assert "LD_LIBRARY_PATH" not in child_environment(unset, True)  # it was empty before


def test_the_waiters_modules_need_nothing_but_the_standard_library() -> None:
    """Imported by every Codex Stop hook, before anything else is loaded."""
    probe = (
        "import sys\n"
        "import app.services.codex_waiter, app.services.chat_wait\n"
        "heavy = ('sqlalchemy', 'alembic', 'pydantic', 'fastapi')\n"
        "print(sorted(m for m in heavy if m in sys.modules))"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, cwd=BACKEND, timeout=60
    )
    assert done.stdout.strip() == "[]", done.stderr


# ---- the waiter queues the decision ----------------------------------------------------------


async def test_an_answer_given_in_review_is_queued_in_the_codex_session_that_asked(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.services.chat_wait import POLL

    w = await world(database_url, tmp_path)
    sub = w["sub"]
    asked = ask(database_url, w, sub)
    bin_ = tmp_path / "bin"
    fake_codex(bin_)
    clock = Clock()
    clock.at[2] = lambda: decide(database_url, w, sub, "answer", "WebP")

    code, out, err = codex_wait(database_url, monkeypatch, capsys, clock, bin_)

    assert (code, out, err) == (0, "", "")  # a detached waiter: nothing for anyone to read
    assert clock.slept == [POLL, POLL]  # one look at once, then every 2 seconds
    [call] = codex_calls(bin_)
    assert call["argv"] == [
        "queue",
        "--thread",
        CODEX,
        "--message",
        answer_text(sub, asked, "WebP", chose=True),
    ]
    got = review_of(database_url, asked)
    assert got["status"] == "answered" and got["delivered_at"] is not None
    assert len(waiting_rows(database_url, CODEX)) == 1  # it noted that it waited


async def test_an_acceptance_with_a_comment_is_queued_and_one_without_is_not(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.services.chat_wait import POLL

    w = await world(database_url, tmp_path)
    sub, notes = w["sub"], w["notes"]
    sent = hand_over(database_url, w, notes, chat=CODEX)
    bin_ = tmp_path / "bin"
    fake_codex(bin_)
    clock = Clock()
    # The report waits for the person: the waiter is alive when they accept it, with a comment.
    clock.at[1] = lambda: decide(database_url, w, notes, "accept", "Good. Add it to the changelog.")

    assert codex_wait(database_url, monkeypatch, capsys, clock, bin_) == (0, "", "")

    assert clock.slept == [POLL]
    [call] = codex_calls(bin_)
    assert call["argv"] == [
        "queue",
        "--thread",
        CODEX,
        "--message",
        "Project Moah Review: the person decided in Review.\n\n"
        f'{notes} "Write the release notes"\n'
        f"You handed over: {HAND_OVER}\n"
        f"The person accepted it and moved {notes} to Done, with this comment: "
        "Good. Add it to the changelog.\n"
        "Next: the task is done. If the comment asks for more work, record it as a new task "
        "(brain_create_task) and do it there; otherwise just acknowledge it briefly.\n\n"
        f"(Moah review ids: {sent})",
    ]
    assert review_of(database_url, sent)["delivered_at"] is not None

    # Accepted without a word: the waiter ends, and nothing is queued or claimed.
    quiet = hand_over(database_url, w, sub, chat=CODEX)
    clock = Clock()
    clock.at[1] = lambda: decide(database_url, w, sub, "accept")
    assert codex_wait(database_url, monkeypatch, capsys, clock, bin_) == (0, "", "")
    assert len(codex_calls(bin_)) == 1
    got = review_of(database_url, quiet)
    assert (got["status"], got["delivered_at"]) == ("accepted", None)


async def test_an_answer_that_is_already_there_is_queued_at_the_first_look(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    w = await world(database_url, tmp_path)
    asked = ask(database_url, w, w["sub"])
    decide(database_url, w, w["sub"], "answer", "PNG")
    bin_ = tmp_path / "bin"
    fake_codex(bin_)
    clock = Clock()

    assert codex_wait(database_url, monkeypatch, capsys, clock, bin_)[0] == 0

    assert clock.slept == [] and len(codex_calls(bin_)) == 1  # no grace, no settling
    assert review_of(database_url, asked)["delivered_at"] is not None


async def test_the_waiter_never_asks_about_a_parent_and_needs_no_input(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    """Detached on purpose: the session may be closed, and the queue still delivers."""
    w = await world(database_url, tmp_path)
    asked = ask(database_url, w, w["sub"])
    bin_ = tmp_path / "bin"
    fake_codex(bin_)
    clock = Clock()
    clock.at[1] = lambda: decide(database_url, w, w["sub"], "answer", "PNG")

    def never() -> int:
        raise AssertionError("a Codex waiter looked for its parent")

    code, out, err = codex_wait(
        database_url, monkeypatch, capsys, clock, bin_, getppid=never, alive=lambda _: False
    )

    assert code == 0 and len(codex_calls(bin_)) == 1
    assert review_of(database_url, asked)["delivered_at"] is not None


async def test_a_chat_with_nothing_open_ends_the_waiter_without_a_call(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    w = await world(database_url, tmp_path)
    ask(database_url, w, w["sub"])
    bin_ = tmp_path / "bin"
    fake_codex(bin_)
    clock = Clock()
    clock.at[1] = lambda: chat_writes(database_url, "WebP, and say so in the notes.")

    code, out, err = codex_wait(database_url, monkeypatch, capsys, clock, bin_)

    assert (code, out, err) == (0, "", "")
    assert codex_calls(bin_) == []  # the person answered in the chat: nothing to hand over
    quiet = Clock()
    nothing = codex_wait(database_url, monkeypatch, capsys, quiet, bin_)
    assert nothing == (0, "", "") and quiet.slept == []  # one that finds nothing open ends at once


async def test_a_newer_waiter_for_the_chat_ends_the_older_one(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.services.chat_wait import register

    w = await world(database_url, tmp_path)
    ask(database_url, w, w["sub"])
    bin_ = tmp_path / "bin"
    fake_codex(bin_)
    clock = Clock()
    path = Path(database_url.removeprefix("sqlite:///"))
    clock.at[1] = lambda: register(path, "codex", CODEX, clock())

    assert codex_wait(database_url, monkeypatch, capsys, clock, bin_)[0] == 0

    assert len(clock.slept) == 1 and codex_calls(bin_) == []
    assert len(waiting_rows(database_url, CODEX)) == 1  # and the older note went


async def test_the_waiter_ends_when_its_day_is_over(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    w = await world(database_url, tmp_path)
    ask(database_url, w, w["sub"])
    clock = Clock()

    code, _, _ = codex_wait(database_url, monkeypatch, capsys, clock, limit=timedelta(seconds=7))

    assert code == 0 and clock.slept == [2.0] * 4  # 2 s looks until the limit, then it ended


async def test_a_waiter_started_by_hand_for_another_agent_does_nothing(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    w = await world(database_url, tmp_path)
    ask(database_url, w, w["sub"])
    env = environment(database_url)
    argv = ["--agent", "someone-else", "--hook", "wait", "--session-id", CODEX]
    assert hook(database_url, monkeypatch, capsys, argv, env, Clock()) == (0, "", "")
    argv = ["--agent", "codex", "--hook", "wait"]  # no chat: nothing to wait for
    assert hook(database_url, monkeypatch, capsys, argv, env, Clock()) == (0, "", "")


# ---- when queueing fails -------------------------------------------------------------------


async def failing_world(database_url: str, tmp_path: Path, clock: Clock):
    w = await world(database_url, tmp_path)
    asked = ask(database_url, w, w["sub"])
    clock.at[1] = lambda: decide(database_url, w, w["sub"], "answer", "WebP")
    return w, asked


async def test_a_codex_that_fails_gives_the_decision_back_and_says_so(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    clock = Clock()
    w, asked = await failing_world(database_url, tmp_path, clock)
    bin_ = tmp_path / "bin"
    fake_codex(bin_, code=1)

    code, out, err = codex_wait(database_url, monkeypatch, capsys, clock, bin_)

    assert (code, out, err) == (0, "", "")  # exit 2 is Claude's way of waking, never Codex's
    assert len(codex_calls(bin_)) == 1
    got = review_of(database_url, asked)
    assert got["status"] == "answered" and got["delivered_at"] is None  # the claim went back
    [error] = logged_errors(database_url)
    assert error["message"] == "wait hook: codex queue ended with code 1"
    assert "queue said no" in error["detail"]
    for private in ("WebP", str(tmp_path), TILES):
        assert private not in json.dumps(error)  # nothing of the person's words, nor of paths

    # The prompt hook hands it over at the person's next message instead (plain standard
    # output, which Codex adds to what the model sees).
    prompt = json.dumps({"session_id": CODEX, "prompt": "Thanks, go on."})
    code, out, err = hook(
        database_url,
        monkeypatch,
        capsys,
        ["--agent", "codex", "--hook", "prompt"],
        environment(database_url),
        stdin=prompt,
    )
    assert code == 0 and err == ""
    assert out == answer_text(w["sub"], asked, "WebP", chose=True) + "\n"
    assert review_of(database_url, asked)["delivered_at"] is not None


async def test_a_codex_that_takes_too_long_is_stopped_and_the_decision_given_back(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    clock = Clock()
    w, asked = await failing_world(database_url, tmp_path, clock)
    bin_ = tmp_path / "bin"
    # Starting Python behind a launcher can take over a second on Windows, and the fake must have
    # written its call down before it is stopped: more time there, and a pause that outlasts it.
    timeout, pause = (4.0, 10) if WINDOWS else (0.7, 30)
    fake_codex(bin_, pause=pause)

    began = time.monotonic()
    code, out, err = codex_wait(
        database_url, monkeypatch, capsys, clock, bin_, queue_timeout=timeout
    )

    assert (code, out, err) == (0, "", "") and time.monotonic() - began < 15
    assert review_of(database_url, asked)["delivered_at"] is None
    [error] = logged_errors(database_url)
    assert error["message"] == f"wait hook: codex queue did not finish in {timeout:g} seconds"
    [call] = codex_calls(bin_)
    deadline = time.monotonic() + 5
    while Path(f"/proc/{call['pid']}").exists() and time.monotonic() < deadline:
        time.sleep(0.05)  # it was killed: nothing is left that could queue the message later
    assert (
        not Path(f"/proc/{call['pid']}").exists()
        or "Z" in Path(f"/proc/{call['pid']}/stat").read_text().split(")")[-1][:3]
    )


async def test_a_computer_without_codex_leaves_the_decision_for_the_prompt_hook(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    clock = Clock()
    w, asked = await failing_world(database_url, tmp_path, clock)
    nowhere = tmp_path / "empty"
    nowhere.mkdir()
    env = environment(database_url, PATH=str(nowhere))

    code, out, err = codex_wait(database_url, monkeypatch, capsys, clock, env=env)

    assert (code, out, err) == (0, "", "")
    assert review_of(database_url, asked)["delivered_at"] is None  # never claimed
    [error] = logged_errors(database_url)
    assert error["message"] == "wait hook: Codex cannot be woken from here"
    assert error["detail"] == "codex was not found"


async def test_the_command_for_codex_in_settings_is_the_one_that_runs(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.services.settings import AgentSettingsUpdate, update_agent_settings

    clock = Clock()
    w, asked = await failing_world(database_url, tmp_path, clock)
    path_one, path_two = tmp_path / "one", tmp_path / "two folder"
    fake_codex(path_one)  # on PATH...
    chosen = fake_codex(path_two, name="codex-beta")  # ...and the person's choice (a space in it)
    with database(database_url) as session:
        update_agent_settings(session, AgentSettingsUpdate(codex_command=str(chosen)))

    assert codex_wait(database_url, monkeypatch, capsys, clock, path_one)[0] == 0

    assert codex_calls(path_one) == [] and len(codex_calls(path_two)) == 1


# ---- Windows: never through cmd.exe ----------------------------------------------------------


def native_exe(shim_folder: Path, package: str = "codex-win32-x64") -> Path:
    """Where npm's Codex keeps its program on Windows (beside its package: inferred from
    bin/codex.js, which was read, not run, on Windows)."""
    triple = "aarch64-pc-windows-msvc" if "arm64" in package else "x86_64-pc-windows-msvc"
    exe = (
        shim_folder / "node_modules" / "@openai" / package / "vendor" / triple / "bin" / "codex.exe"
    )
    exe.parent.mkdir(parents=True)
    exe.write_text("MZ")
    return exe


def test_on_windows_only_a_real_program_is_ever_given_the_persons_words(tmp_path: Path) -> None:
    from app.services.codex_waiter import resolve_codex

    def find(configured=None, *folders: Path, machine="AMD64"):
        env = {"PATH": os.pathsep.join(str(f) for f in folders)}
        return resolve_codex(configured, env, windows=True, machine=machine)

    npm, apps, cheap = tmp_path / "npm", tmp_path / "apps", tmp_path / "cheap"
    for folder in (npm, apps, cheap):
        folder.mkdir()
    (npm / "codex.cmd").write_text("@echo off")
    (npm / "codex.ps1").write_text("")
    (npm / "codex").write_text("#!/bin/sh")  # npm's sh script: not for Windows either

    # Only the shim: no program, and the reason says why and what to do.
    found = find(None, npm)
    assert found.command is None and "codex.cmd" in found.problem and "cmd.exe" in found.problem

    # The package's own program beside the shim is the one to run (and nothing else of it).
    exe = native_exe(npm)
    assert find(None, npm).command == [str(exe)]
    arm = native_exe(cheap, "codex-win32-arm64")
    (cheap / "codex.bat").write_text("@echo off")
    assert find(None, cheap, machine="ARM64").command == [str(arm)]
    assert find(None, cheap, machine="AMD64").command is None  # an x64 program is not there

    # A real program anywhere on PATH wins over a shim that comes first, and .exe over .cmd in
    # one folder.
    (apps / "codex.exe").write_text("MZ")
    assert find(None, npm, apps).command == [str(exe)]  # the shim's own program, found first
    (npm / "node_modules" / "@openai" / "codex-win32-x64").rename(tmp_path / "gone")
    assert find(None, npm, apps).command == [str(apps / "codex.exe")]
    (npm / "codex.exe").write_text("MZ")
    assert find(None, npm).command == [str(npm / "codex.exe")]

    # A configured command: a path, a path with arguments, a quoted path with a space, a shim.
    spaced = tmp_path / "Program Files" / "Codex"
    spaced.mkdir(parents=True)
    (spaced / "codex.exe").write_text("MZ")
    assert find(str(spaced / "codex.exe")).command == [str(spaced / "codex.exe")]
    assert find(str(spaced / "codex")).command == [str(spaced / "codex.exe")]  # no extension
    assert find(f'"{spaced / "codex.exe"}" --profile x').command == [
        str(spaced / "codex.exe"),
        "--profile",
        "x",
    ]
    only_shim = tmp_path / "shim"
    only_shim.mkdir()
    (only_shim / "codex.cmd").write_text("@echo off")
    assert find(str(only_shim / "codex.cmd")).command is None
    assert find("   ").problem == "the command for Codex in Settings is empty"
    assert find("nothing-here", npm).command is None


@pytest.mark.skipif(WINDOWS, reason="a file that is not executable cannot be made on Windows")
def test_on_other_systems_codex_is_found_on_path_as_the_shell_would(tmp_path: Path) -> None:
    from app.services.codex_waiter import resolve_codex

    folder, other = tmp_path / "a", tmp_path / "b"
    folder.mkdir()
    other.mkdir()
    (folder / "codex").write_text("not runnable")  # on PATH, but not executable
    program = fake_codex(other)
    env = {"PATH": f"{folder}{os.pathsep}{other}"}
    assert resolve_codex(None, env, windows=False).command == [str(program)]
    assert resolve_codex("codex --profile work", env, windows=False).command == [
        str(program),
        "--profile",
        "work",
    ]
    assert resolve_codex(str(program), {}, windows=False).command == [str(program)]
    assert resolve_codex(None, {"PATH": str(folder)}, windows=False).command is None


def test_npms_layout_is_what_the_real_package_has(tmp_path: Path) -> None:
    """native_program finds the program where Codex's own script does, checked on a real
    package when there is one (the Windows names are the same layout with other names)."""
    from app.services.codex_waiter import native_program

    program = real_codex()
    if program is None:
        pytest.skip("no codex program: set MOAH_TEST_CODEX")
    shim = Path(program).resolve()
    if shim.name != "codex.js":
        pytest.skip("not the npm package")
    import platform

    found = native_program(Path(program).parent, False, platform.machine())
    assert found is not None and found.is_file() and found.parent.name == "bin"
    assert subprocess.run([found, "--version"], capture_output=True, timeout=30).returncode == 0


async def test_a_windows_shim_is_never_run_and_its_own_program_is(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    clock = Clock()
    w, asked = await failing_world(database_url, tmp_path, clock)
    npm = tmp_path / "npm"
    shim = fake_codex(npm, name="codex.cmd")  # would run on this computer; must not
    clock_two = Clock()

    # (The program npm ships is for the machine's own processor, whichever this one is.)
    env = environment(
        database_url, PATH=str(npm), PROCESSOR_ARCHITECTURE="AMD64", PROCESSOR_ARCHITEW6432=""
    )
    code, out, err = codex_wait(database_url, monkeypatch, capsys, clock, env=env, windows=True)

    assert (code, out, err) == (0, "", "")
    assert codex_calls(npm) == [] and shim.exists()
    assert review_of(database_url, asked)["delivered_at"] is None
    [error] = logged_errors(database_url)
    assert "only a script" in error["detail"] and "codex.cmd" in error["detail"]

    # With the package's own program there, that one runs, without a console window.
    exe = write_program(native_exe(npm), fake_source(npm / "codex.log"))
    real_popen = subprocess.Popen
    seen = []

    def popen(command, **options):
        seen.append((command, options.pop("creationflags", None)))
        options.pop("start_new_session", None)
        return real_popen(command, **options)

    monkeypatch.setattr(subprocess, "Popen", popen)
    code, out, err = codex_wait(database_url, monkeypatch, capsys, clock_two, env=env, windows=True)
    assert (code, out, err) == (0, "", "")
    [(command, flags)] = seen
    assert command[0] == str(exe) and command[1:4] == ["queue", "--thread", CODEX]
    assert flags == 0x08000000  # CREATE_NO_WINDOW: a console program from a detached process
    assert len(codex_calls(npm)) == 1
    assert review_of(database_url, asked)["delivered_at"] is not None


# ---- the message ---------------------------------------------------------------------------


def test_a_long_message_is_cut_from_the_middle_and_keeps_its_first_and_last_lines() -> None:
    from app.services.chat_delivery import DELIVERY_MARKER, delivery_ids, is_delivery
    from app.services.codex_waiter import CUT_NOTE, MESSAGE_LIMIT, fit_message

    ids = "(Moah review ids: 2f1, 8a4)"
    short = f"{DELIVERY_MARKER}\n\nHARB-2 task\nThe person chose: PNG\n\n{ids}"
    assert fit_message(short) == short and fit_message(short + "\n\n") == short
    long = f"{DELIVERY_MARKER}\n\n" + "A line of the person's words.\n" * 1000 + f"\n{ids}"
    fitted = fit_message(long)
    assert MESSAGE_LIMIT == 8000 and len(fitted) <= MESSAGE_LIMIT
    lines = fitted.splitlines()
    assert lines[0] == DELIVERY_MARKER and lines[-1] == ids and is_delivery(fitted)
    assert delivery_ids(fitted) == ["2f1", "8a4"]
    assert f"… {CUT_NOTE}\n" in fitted and "A line of the person's words." in fitted
    assert len(fit_message(long, 500)) <= 500
    assert len(fit_message("x\n" + "y" * 20000 + "\nz", 100)) <= 100  # even with a tiny room


@pytest.mark.parametrize("flags", [(), ("--print",)])
async def test_a_message_longer_than_a_command_line_takes_is_cut_with_its_ids_kept(
    database_url: str, tmp_path: Path, monkeypatch, capsys, flags
) -> None:
    from app.services.chat_delivery import DELIVERY_MARKER, delivery_ids

    w = await world(database_url, tmp_path)
    notes = w["notes"]
    reviews = {
        w["sub"]: ask(database_url, w, w["sub"]),
        notes: ask(database_url, w, notes, question="Ship the notes in English only?"),
        w["orchestrator"]: ask(database_url, w, w["orchestrator"], question="Cut the scope?"),
    }
    bin_ = tmp_path / "bin"
    fake_codex(bin_)
    clock = Clock()

    def answer() -> None:
        for ref in reviews:
            decide(database_url, w, ref, "answer", "Mind the zoom levels. " * 200)

    clock.at[1] = answer
    code, out, err = codex_wait(database_url, monkeypatch, capsys, clock, bin_, flags=flags)

    assert code == 0
    if flags:  # the shell line gets the same message, after the thread and the ids
        message = out.split("\n", 2)[2].rstrip("\n")
    else:
        [call] = codex_calls(bin_)
        message = call["argv"][-1]
    assert len(message) <= 8000
    assert message.splitlines()[0] == DELIVERY_MARKER
    assert sorted(delivery_ids(message)) == sorted(reviews.values())  # every id named
    assert "(cut: the rest is in Moah)" in message
    assert all(review_of(database_url, r)["delivered_at"] is not None for r in reviews.values())


async def test_a_queued_message_fed_back_to_the_prompt_hook_settles_nothing(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    """The queued text fires Codex's prompt hook like a message of the person's own."""
    from app.services.codex_waiter import fit_message

    w, first, second = await two_answers(database_url, tmp_path)
    open_one = ask(database_url, w, w["orchestrator"], question="Cut the scope?")
    decide(database_url, w, w["sub"], "answer", "Mind the zoom levels. " * 300)
    decide(database_url, w, w["notes"], "answer", "Yes.")
    from app.services.chat_delivery import deliver

    sent: list[str] = []
    with database(database_url) as session:
        assert deliver(session, CODEX, sent.append)  # what the waiter does before it queues
    [text] = sent
    for queued in (text, fit_message(text, 400)):
        code, out, err = hook(
            database_url,
            monkeypatch,
            capsys,
            ["--agent", "codex", "--hook", "prompt"],
            environment(database_url),
            stdin=json.dumps({"session_id": CODEX, "prompt": queued}),
        )
        assert code == 0 and err == ""
        assert review_of(database_url, open_one)["status"] == "pending"  # not "the reply"
    chat_writes(database_url, "Yes, go on.")  # while the person's own words do settle it
    assert review_of(database_url, open_one)["status"] == "answered"
    assert capsys.readouterr().out == ""  # and handed nothing over: it was all claimed


# ---- --print and --hook release (the Flatpak's pieces) ------------------------------------


async def test_print_mode_claims_and_prints_the_thread_the_ids_and_the_message(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    w, first, second = await two_answers(database_url, tmp_path)
    clock = Clock()

    def answer() -> None:
        decide(database_url, w, w["sub"], "answer", NASTY)
        decide(database_url, w, w["notes"], "answer", "Yes.")

    clock.at[2] = answer

    code, out, err = codex_wait(database_url, monkeypatch, capsys, clock, flags=["--print"])

    assert code == 0 and err == ""
    thread, ids, message = out.split("\n", 2)
    assert thread == CODEX and ids.split(" ") == [first, second]
    assert message.startswith("Project Moah Review: the person decided in Review.\n\n")
    assert f"The person answered: {NASTY}\n" in message and "The person answered: Yes." in message
    assert message.endswith(f"(Moah review ids: {first}, {second})\n")
    assert review_of(database_url, first)["delivered_at"] is not None  # claimed: the shell sends


async def test_print_mode_prints_nothing_when_nothing_was_claimed(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    w = await world(database_url, tmp_path)
    asked = ask(database_url, w, w["sub"])
    clock = Clock()

    code, out, err = codex_wait(
        database_url, monkeypatch, capsys, clock, flags=["--print"], limit=timedelta(seconds=5)
    )

    assert (code, out, err) == (0, "", "")  # the day ended, no answer: not a character
    assert review_of(database_url, asked)["delivered_at"] is None


async def test_print_mode_gives_the_claim_back_when_the_shell_has_gone(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    w = await world(database_url, tmp_path)
    asked = ask(database_url, w, w["sub"])
    decide(database_url, w, w["sub"], "answer", "PNG")

    def gone(_: str) -> None:
        raise BrokenPipeError("the reader ended")

    code, out, err = codex_wait(
        database_url, monkeypatch, capsys, Clock(), flags=["--print"], show=gone
    )

    assert (code, out, err) == (0, "", "")
    assert review_of(database_url, asked)["delivered_at"] is None
    assert logged_errors(database_url)[0]["message"] == "wait hook: BrokenPipeError"


async def test_release_gives_claimed_decisions_back_and_touches_nothing_else(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    from app.services.chat_delivery import deliver

    w, first, second = await two_answers(database_url, tmp_path)
    third = hand_over(database_url, w, w["orchestrator"], chat=CODEX)
    decide(database_url, w, w["sub"], "answer", "PNG")
    decide(database_url, w, w["notes"], "answer", "Yes.")
    decide(database_url, w, w["orchestrator"], "accept")  # no words: nothing to hand over
    with database(database_url) as session:
        assert deliver(session, CODEX, lambda _: None)
    claimed = [r for r in (first, second, third) if review_of(database_url, r)["delivered_at"]]
    assert sorted(claimed) == sorted([first, second])
    env = environment(database_url)

    for ids in (f"{first};DROP TABLE task_reviews", "", "nonsense ../x"):
        hook(database_url, monkeypatch, capsys, release_argv(ids), env)
        assert all(review_of(database_url, r)["delivered_at"] for r in (first, second))

    assert hook(database_url, monkeypatch, capsys, release_argv(first), env) == (0, "", "")
    assert review_of(database_url, first)["delivered_at"] is None
    assert review_of(database_url, second)["delivered_at"] is not None
    # Both, in the spelling the shell passes, and one that is no decision any more.
    assert hook(database_url, monkeypatch, capsys, release_argv(f"{first}  {second}"), env)[0] == 0
    assert review_of(database_url, second)["delivered_at"] is None
    assert review_of(database_url, third)["status"] == "accepted"
    assert review_of(database_url, third)["delivered_at"] is None
    # A decision that is none any more (the agent replaced the question since) keeps its mark.
    with database(database_url) as session:
        from app.models.review import TaskReview

        session.get(TaskReview, second).status = "replaced"
        session.get(TaskReview, second).delivered_at = session.get(TaskReview, first).created_at
        session.commit()
    hook(database_url, monkeypatch, capsys, release_argv(second), env)
    assert review_of(database_url, second)["delivered_at"] is not None
    # No database at all, and no ids at all: still 0, still silent.
    gone = environment(database_url, PROJECT_BRAIN_DATABASE_URL=f"sqlite:///{tmp_path}/no.db")
    assert hook(database_url, monkeypatch, capsys, release_argv(first), gone) == (0, "", "")
    assert hook(database_url, monkeypatch, capsys, ["--hook", "release"], env) == (0, "", "")


def release_argv(ids: str) -> list[str]:
    return ["--agent", "codex", "--hook", "release", "--ids", ids]


# ---- the Flatpak's hook line, for real -------------------------------------------------------

FLATPAK = ["flatpak", "run", "--command=project-moah-mcp", "io.github.projectbrain.ProjectBrain"]


def test_the_flatpaks_stop_line_is_this_one() -> None:
    from app.services.codex_waiter import flatpak_stop_line

    moah = "flatpak run --command=project-moah-mcp io.github.projectbrain.ProjectBrain"
    assert flatpak_stop_line(FLATPAK) == (
        f'd=$(cat); printf %s "$d" | {moah} --agent codex --hook stop >/dev/null 2>&1; '
        "if command -v setsid >/dev/null 2>&1; then s=setsid; else s=nohup; fi; "
        '{ printf %s "$d" | $s sh -c \''
        f"{moah} --agent codex --hook wait --print"
        ' | { read -r t && read -r i && m=$(cat) && { codex queue --thread "$t" --message "$m"'
        f' || {moah} --agent codex --hook release --ids "$i"; }}; }}\'; }} '
        ">/dev/null 2>&1 </dev/null &"
    )


class Flatpak:
    """A Flatpak, near enough: Moah as ``python wrapper.py``, which says it is sandboxed (the
    ``/.flatpak-info`` file is what it looks for), and a fake ``codex`` on PATH."""

    def __init__(self, database_url: str, tmp_path: Path, spaced: bool = False, **codex) -> None:
        """``spaced``: the programs sit in folders with a space in their names, and Codex is
        named by its path, as a person with such a path would have it."""
        self.url = database_url
        self.bin = tmp_path / ("host bin" if spaced else "host-bin")
        fake_codex(self.bin, **codex)
        self.codex = str(self.bin / "codex") if spaced else "codex"
        info = tmp_path / "flatpak-info"
        info.write_text("[Application]\n")
        wrapper = tmp_path / ("my moah" if spaced else "moah") / "moah.py"
        wrapper.parent.mkdir()
        wrapper.write_text(
            "import pathlib, runpy, sys\n"
            # What `flatpak run` can say on its own streams (a warning, a portal message).
            "if 'stop' in sys.argv:\n"
            "    print('flatpak: a warning'); print('flatpak: a warning', file=sys.stderr)\n"
            "from app.services import codex_waiter\n"
            f"codex_waiter.FLATPAK_INFO = pathlib.Path({str(info)!r})\n"
            "runpy.run_module('app.mcp', run_name='__main__')\n"
        )
        self.moah = [sys.executable, str(wrapper)]
        self.tmp = tmp_path

    def run(
        self,
        shell: str = "sh",
        path: str | None = None,
        message: str = "Done.",
        chat=CODEX,
        own_group: bool = False,
    ):
        """Codex runs its Stop hook line through a shell, with its JSON on standard input.
        Returns the shell's exit code, its output and the seconds it took. ``own_group``: the
        line runs in a process group of its own (``end_group`` kills it, as an agent may clean
        up after a hook)."""
        from app.services.codex_waiter import flatpak_stop_line

        env = environment(self.url, self.bin)
        if path is not None:
            env["PATH"] = path
        line = flatpak_stop_line(self.moah, self.codex)
        payload = json.dumps({"session_id": chat, "last_assistant_message": message})
        began = time.monotonic()
        shell_process = subprocess.Popen(
            [shell, "-c", line],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            cwd=self.tmp,
            start_new_session=own_group,
        )
        self.group = shell_process.pid
        # communicate() waits for the end of the output: a background job that kept Codex's
        # pipes would keep this waiting until it ended itself.
        out, err = shell_process.communicate(payload, timeout=30)
        return shell_process.returncode, out, err, time.monotonic() - began

    def waiters(self) -> list[int]:
        """The waiters this Flatpak started (its own wrapper's path is in their command lines,
        so a leftover of another run is not counted)."""
        return processes(self.moah[1], "wait", "--print")

    def end_all(self) -> None:
        end_all(self.moah[1], "--print")

    def end_group(self) -> None:
        import signal

        try:
            os.killpg(self.group, signal.SIGKILL)
        except ProcessLookupError:
            pass  # nothing of the line was left in it


def processes(*words: str) -> list[int]:
    """Processes started with all these words as arguments, on Linux."""
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            parts = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if all(word.encode() in parts for word in words):
            found.append(int(entry.name))
    return found


def end_all(*words: str, only: set[int] | None = None) -> None:
    import signal

    for pid in processes(*words):
        if only is not None and pid not in only:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc")
@pytest.mark.parametrize(("shell", "spaced"), [("sh", False), ("bash", False), ("sh", True)])
async def test_the_flatpaks_line_returns_at_once_and_the_waiter_it_started_queues_the_answer(
    database_url: str, tmp_path: Path, shell: str, spaced: bool
) -> None:
    w = await world(database_url, tmp_path)
    sub = w["sub"]
    asked = ask(database_url, w, sub)
    flatpak = Flatpak(database_url, tmp_path, spaced)
    try:
        code, out, err, seconds = flatpak.run(shell, own_group=True)

        print(f"the hook line ({shell}, spaced={spaced}) returned after {seconds:.2f} seconds")
        assert (code, out, err) == (0, "", "")  # Codex gets nothing: no output, no error
        assert seconds < 2, f"the hook line held Codex up for {seconds:.1f} seconds"
        wait_until(lambda: waiting_rows(database_url, CODEX), [], "the waiter began to wait")
        flatpak.end_group()  # an agent cleaning up after the hook: its process group goes
        time.sleep(0.5)
        assert len(flatpak.waiters()) == 1  # the line is over; the waiter is not
        assert codex_calls(flatpak.bin) == []
        assert review_of(database_url, asked)["delivered_at"] is None

        decide(database_url, w, sub, "answer", NASTY)
        wait_until(lambda: codex_calls(flatpak.bin), [], "codex queue was run")
        wait_until(lambda: not flatpak.waiters(), [], "the waiter ended")
    finally:
        flatpak.end_all()

    [call] = codex_calls(flatpak.bin)
    assert call["argv"][:4] == ["queue", "--thread", CODEX, "--message"] and len(call["argv"]) == 5
    assert call["argv"][4] == answer_text(sub, asked, NASTY)  # quotes, $, backticks, & and all
    assert review_of(database_url, asked)["delivered_at"] is not None  # and it stays handed over
    assert logged_errors(database_url) == []


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc")
async def test_when_codex_queue_fails_the_flatpaks_line_gives_the_decision_back(
    database_url: str, tmp_path: Path
) -> None:
    w = await world(database_url, tmp_path)
    asked = ask(database_url, w, w["sub"])
    flatpak = Flatpak(database_url, tmp_path, code=1)
    try:
        assert flatpak.run()[:3] == (0, "", "")
        wait_until(lambda: waiting_rows(database_url, CODEX), [], "the waiter began to wait")
        decide(database_url, w, w["sub"], "answer", "WebP")
        wait_until(lambda: codex_calls(flatpak.bin), [], "codex queue was run")
        wait_until(
            lambda: review_of(database_url, asked)["delivered_at"] is None,
            [],
            "the decision was given back",
        )
    finally:
        flatpak.end_all()
    assert len(codex_calls(flatpak.bin)) == 1
    assert review_of(database_url, asked)["status"] == "answered"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc")
async def test_the_flatpaks_line_works_without_setsid_and_with_a_turn_that_has_nothing_open(
    database_url: str, tmp_path: Path
) -> None:
    w = await world(database_url, tmp_path)
    sub = w["sub"]
    asked = ask(database_url, w, sub)
    flatpak = Flatpak(database_url, tmp_path)
    tools = tmp_path / "tools"  # a PATH of what the line needs, and no setsid
    tools.mkdir()
    for name in ("cat", "nohup"):
        os.symlink(shutil.which(name), tools / name)
    os.symlink("/bin/sh", tools / "sh")
    os.symlink(flatpak.bin / "codex", tools / "codex")
    assert shutil.which("setsid", path=str(tools)) is None
    try:
        code, out, err, seconds = flatpak.run("/bin/sh", path=str(tools))
        assert (code, out, err) == (0, "", "") and seconds < 2
        wait_until(lambda: waiting_rows(database_url, CODEX), [], "the waiter began to wait")
        decide(database_url, w, sub, "answer", "PNG")
        wait_until(lambda: codex_calls(flatpak.bin), [], "codex queue was run")
    finally:
        flatpak.end_all()
    [call] = codex_calls(flatpak.bin)
    assert call["argv"][4] == answer_text(sub, asked, "PNG", chose=True)

    # A chat that has nothing open: the line records, the waiter finds nothing and ends, and no
    # call is ever made.
    other = tmp_path / "second"
    other.mkdir()
    quiet = Flatpak(database_url, other)
    assert quiet.run(chat=OTHER)[:3] == (0, "", "")
    time.sleep(1.5)  # the waiter starts, finds nothing open for that chat, and is gone
    assert quiet.waiters() == [] and codex_calls(quiet.bin) == []
    assert waiting_rows(database_url, OTHER) == []


# ---- real processes --------------------------------------------------------------------------


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc")
async def test_the_real_stop_hook_starts_a_waiter_that_outlives_it_and_queues_the_answer(
    database_url: str, tmp_path: Path
) -> None:
    from tests.test_chat_delivery import resident_megabytes

    w = await world(database_url, tmp_path)
    sub = w["sub"]
    asked = ask(database_url, w, sub)
    bin_ = tmp_path / "bin"
    fake_codex(bin_)
    payload = json.dumps(
        {"session_id": CODEX, "hook_event_name": "Stop", "last_assistant_message": "Done."}
    )
    before = set(processes("wait", CODEX))  # a leftover of some other run is not ours
    began = time.monotonic()
    try:
        stop_hook = subprocess.run(
            [*MOAH_TOOL, "--agent", "codex", "--hook", "stop"],
            input=payload,
            capture_output=True,
            text=True,
            cwd=BACKEND,
            env=environment(database_url, bin_),
            timeout=60,
        )
        # Codex waits for the hook's output to end: nothing keeps it open, and nothing is printed.
        assert (stop_hook.returncode, stop_hook.stdout, stop_hook.stderr) == (0, "", "")
        assert time.monotonic() - began < 5
        wait_until(lambda: waiting_rows(database_url, CODEX), [], "the waiter began to wait")
        [waiter] = set(processes("wait", CODEX)) - before
        assert os.getsid(waiter) == waiter  # a session of its own: Codex's group never reaches it
        for number in (0, 1, 2):
            assert os.readlink(f"/proc/{waiter}/fd/{number}") == "/dev/null"
        rss = resident_megabytes(waiter)
        print(f"the detached Codex waiter: {rss} MB resident")
        assert rss is None or rss < 40
        assert codex_calls(bin_) == []

        decide(database_url, w, sub, "answer", NASTY)
        wait_until(lambda: codex_calls(bin_), [], "codex queue was run")
        wait_until(lambda: waiter not in processes("wait", CODEX), [], "the waiter ended")
    finally:
        end_all("wait", CODEX, only=set(processes("wait", CODEX)) - before)
    [call] = codex_calls(bin_)
    assert call["argv"] == ["queue", "--thread", CODEX, "--message", answer_text(sub, asked, NASTY)]
    assert review_of(database_url, asked)["delivered_at"] is not None
    assert sqlite3.connect(database_url.removeprefix("sqlite:///")).execute(
        "PRAGMA integrity_check"
    ).fetchone() == ("ok",)


def real_codex() -> str | None:
    return os.environ.get("MOAH_TEST_CODEX") or shutil.which("codex")


def codex_home(folder: Path, thread: str | None = None) -> Path:
    """A throwaway CODEX_HOME, with a stored session if there is a ``thread``: all that
    ``codex queue`` needs to queue a message for a session that is not open (one line, made up)."""
    home = folder / "codex-home"
    if thread:
        rollout = (
            home / "sessions" / "2026" / "11" / "22" / f"rollout-2026-11-22T10-00-00-{thread}.jsonl"
        )
        rollout.parent.mkdir(parents=True)
        meta = {
            "session_id": thread,
            "id": thread,
            "timestamp": "2026-11-22T10:00:00.000Z",
            "cwd": str(folder),
            "originator": "codex-tui",
            "cli_version": "0.163.0",
            "source": "cli",
            "thread_source": "user",
            "model_provider": "fake",
        }
        line = {"timestamp": "2026-11-22T10:00:00.000Z", "ordinal": 0, "type": "session_meta"}
        rollout.write_text(json.dumps({**line, "payload": meta}) + "\n")
    else:
        home.mkdir()
    return home


async def real_queue(database_url, tmp_path, monkeypatch, capsys, thread_known: bool):
    from app.services.settings import AgentSettingsUpdate, update_agent_settings

    program = real_codex()
    if program is None:
        pytest.skip("no codex program: set MOAH_TEST_CODEX")
    clock = Clock()
    w, asked = await failing_world(database_url, tmp_path, clock)
    home = codex_home(tmp_path, CODEX if thread_known else None)
    with database(database_url) as session:
        update_agent_settings(session, AgentSettingsUpdate(codex_command=program))
    env = environment(database_url, CODEX_HOME=str(home))
    result = codex_wait(database_url, monkeypatch, capsys, clock, env=env, queue_timeout=60)
    return w, asked, home, result


async def test_the_real_codex_takes_the_queued_message_intact(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    """``codex queue`` itself, against a throwaway CODEX_HOME that holds the session (what a
    closed session is). The model is never involved: the message waits in Codex's queue."""
    w, asked, home, result = await real_queue(database_url, tmp_path, monkeypatch, capsys, True)

    assert result == (0, "", "")
    assert review_of(database_url, asked)["delivered_at"] is not None
    assert logged_errors(database_url) == []
    queued = (
        sqlite3.connect(home / "queue_1.sqlite")
        .execute("SELECT thread_id, payload_json FROM queued_items")
        .fetchall()
    )
    [(thread, item)] = queued
    assert thread == CODEX
    [content] = json.loads(item)["UserInput"]["content"]
    assert content["text"] == answer_text(w["sub"], asked, "WebP", chose=True)


async def test_the_real_codex_refuses_a_session_it_does_not_know_and_the_decision_goes_back(
    database_url: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    w, asked, home, result = await real_queue(database_url, tmp_path, monkeypatch, capsys, False)

    assert result == (0, "", "")
    assert review_of(database_url, asked)["delivered_at"] is None
    [error] = logged_errors(database_url)
    assert error["message"] == "wait hook: codex queue ended with code 1"
    assert "no rollout found" in error["detail"]

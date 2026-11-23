"""What the person decides in Review reaches the chat: the Stop hook's two commands for Claude Code.

Agents ask in the chat, the question waits in Review, and the person often answers there. Claude
Code's Stop event runs two Moah commands side by side (Connect writes them, step 5; a hook may be
a background one that wakes the session, ``asyncRewake``):

    {"type": "command", "command": "<moah> --agent claude --hook stop --settle",
     "async": true, "timeout": 60}
    {"type": "command", "command": "<moah> --agent claude --hook wait",
     "asyncRewake": true, "timeout": 86400}

and the prompt hook, in the same way (the person writes in the chat):

    {"type": "command", "command": "<moah> --agent claude --hook prompt --deliver",
     "asyncRewake": true, "timeout": 60}

Codex's prompt hook stays a plain synchronous one: ``<moah> --agent codex --hook prompt``.

``--hook stop`` only records (chat_questions.record_stop) and always exits 0. With ``--settle`` it
first waits SETTLE seconds, so a message the person is already writing gets there first, and
records nothing when the person did write in the chat meanwhile: that message answers the
question. Without the flag it is the hook as it was written before this version, and does as it
did (a line Connect wrote earlier keeps working until Connect refreshes it).

``--hook wait`` is the waiter (``handle``). It records nothing and settles for nothing, and in
order (this is Claude Code's; Codex's differs where the last paragraph says):

1. Every POLL seconds it looks for a decision to hand over (chat_delivery.undelivered). Found: it
   claims it (``delivered_at``), writes the message to standard error and exits 2, which wakes the
   chat with that text.
2. It ends, exit 0, when the chat has nothing open in Review: no pending question or report
   stamped with this chat, no unstamped one on the chat's task, no task of the chat waiting for
   review without a stored report, and no decision the chat was not told of yet. Not during its
   first GRACE seconds when the turn ended on a question: the record command runs in parallel and
   may not have written it yet. When the turn did not (most turns), it looks once at once and
   once more after SETTLE seconds, which is all a late stamp of the tool hook (a question the
   agent asked through Moah, written a second or two after the call) needs; nothing open then
   ends it without a note in the database.
3. Once something is open it notes in ``agent_session_events`` (source ``waiting``) that it waits
   for this chat. A newer waiter for the same chat supersedes it.
4. It also ends once a newer waiter took over, WAIT_LIMIT has passed (Claude Code stops a hook at
   its timeout, 24 hours), the hook's parent is gone (the agent was closed), or anything fails.

Exit code 2 is how a hook wakes Claude Code, so it is the one thing a failure must never cause:
only a delivery returns 2, and every error ends the hook with 0 (the prompt hook hands the decision
over later, chat_delivery.prompt_delivery).

Codex's waiter (``--agent codex --hook wait``, started detached by its Stop hook, see
codex_waiter.py) takes the chat from ``--session-id``, because it has no input; looks at once and
then every POLL seconds with no grace and no settling (its Stop hook recorded synchronously before
it started); never looks at a parent; and hands a decision over with ``codex queue`` (``--print``:
prints it for a shell that does). It always exits 0. ``--hook release --ids`` gives decisions back
(``delivered_at`` empty again) for the shell line that could not queue them.

This module uses only the standard library until a decision is found: a waiter polls a read-only
SQLite connection, because a waiter lives for hours and Project Moah itself takes about 45 MB more
memory than the 17 MB such a waiter needs. The SQL below must say what chat_delivery.undelivered
says; a test runs both on the same rows. Nothing here goes online.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import traceback
from collections.abc import Callable, Mapping
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NamedTuple

from app.services.hook_text import (
    hook_agent,
    hook_kind,
    nothing_to_record,
    option_value,
    question_parts,
    read_hook_input,
    stop_message,
    valid_id,
)

# Seconds a hook gives a message the person is writing, before it records or hands over:
# one that arrives in that time answers the question, or the decision, in the chat itself.
SETTLE = 3.0
POLL = 2.0  # seconds between two looks at Review
GRACE = (
    30.0  # seconds a waiter keeps looking although nothing is open yet (the record hook runs too)
)
WAIT_LIMIT = timedelta(hours=23, minutes=30)  # a waiter ends this long after its turn ended
BUSY_SECONDS = 5.0  # how long a read or a write waits for another process (as db/session.py)
MAX_MISSES = 5  # looks that found a decision the full reader then could not claim, in a row
QUEUE_TIMEOUT = 60.0  # seconds ``codex queue`` may take (codex_waiter.queue)
RELEASE_LIMIT = 50  # decisions one ``--hook release`` gives back
# A decision older than this is not handed over any more: the work moved on without it.
DELIVERY_WINDOW = timedelta(days=7)
# What the lean queries below need from the rest of Project Moah, spelled out because this module
# cannot import it: services/reviews.py ANSWERED_IN_CHAT, services/agent_sessions.py
# TASK, HOOK_TASK, PROMPT and WAITING. A test compares them.
ANSWERED_IN_CHAT = "chat"
DELIVERABLE_STATUSES = ("answered", "rejected", "accepted")
WAITING = "waiting"

Write = Callable[[str], None]
Deliver = Callable[[str, datetime, Write], bool]

# The decisions to hand over: the person's answer to a question, a send-back (including one that
# reopened accepted work), or an acceptance that came with a comment or a file, given in Review
# and not yet delivered. Not an answer given in the chat, not an acceptance without words (it
# wakes nobody), nothing a drag on the board decided without a word, and nothing the agent
# already handed over again since.
DELIVERABLE = """
SELECT r.id FROM task_reviews r
WHERE r.session_id = :chat
  AND r.status IN ('answered', 'rejected', 'accepted')
  AND (r.moved_to IS NULL OR r.moved_to != 'chat')
  AND r.delivered_at IS NULL
  AND r.reviewed_at >= :since
  AND (r.comment IS NOT NULL OR EXISTS (
        SELECT 1 FROM review_files f WHERE f.review_id = r.id AND f.kind = 'feedback'))
  AND NOT EXISTS (
        SELECT 1 FROM task_reviews n WHERE n.task_id = r.task_id AND n.round > r.round)
ORDER BY r.reviewed_at, r.round
"""
# The chat's task, as chat_questions.session_task finds it.
SESSION_TASK = """
SELECT task_id FROM agent_session_events
WHERE agent = :agent AND session_id = :chat AND task_id IS NOT NULL
  AND source IN ('task', 'hook_task', 'prompt')
ORDER BY created_at DESC, id DESC LIMIT 1
"""
# Whether the chat has something open: a question or report of its own waiting for the person,
# one nobody stamped on the chat's task (the person's answer goes to the chat that worked on the
# task), or the chat's task waiting in Review with no report stored yet (Review drafts one).
OPEN = """
SELECT 1 WHERE
  EXISTS (SELECT 1 FROM task_reviews WHERE session_id = :chat AND status = 'pending')
  OR EXISTS (SELECT 1 FROM task_reviews
             WHERE task_id = :task AND session_id IS NULL AND status = 'pending')
  OR (EXISTS (SELECT 1 FROM tasks WHERE id = :task AND status = 'review')
      AND NOT EXISTS (SELECT 1 FROM task_reviews WHERE task_id = :task AND status = 'pending'))
"""


def _now() -> datetime:
    return datetime.now(UTC)


def stamp(at: datetime) -> str:
    """A time the way SQLAlchemy stores it in SQLite: UTC, as text, so times compare as text."""
    at = at.replace(tzinfo=UTC) if at.tzinfo is None else at.astimezone(UTC)
    return at.strftime("%Y-%m-%d %H:%M:%S.%f")


# ---- the database, without loading Project Moah ------------------------------------------


def database_file(environ: Mapping[str, str] | None = None) -> Path | None:
    """The SQLite file Project Moah uses, found as core/config.get_database_url does (which
    this module cannot import: it loads SQLAlchemy). None when the database is not a plain file,
    so there is nothing to look at."""
    environ = os.environ if environ is None else environ
    if url := environ.get("PROJECT_BRAIN_DATABASE_URL"):
        prefix = next((p for p in ("sqlite:///", "sqlite+pysqlite:///") if url.startswith(p)), None)
        name = url[len(prefix) :] if prefix else ""
        if not name or name == ":memory:" or "?" in name or "%" in name:
            return None
        return Path(name)
    if explicit := environ.get("PROJECT_BRAIN_DB_PATH"):
        return Path(explicit).expanduser().resolve()
    if sys.platform == "win32":
        local_app_data = environ.get("LOCALAPPDATA")
        data_home = (
            Path(local_app_data)
            if local_app_data and Path(local_app_data).is_absolute()
            else Path.home() / "AppData" / "Local"
        )
    else:
        xdg_data_home = environ.get("XDG_DATA_HOME")
        data_home = (
            Path(xdg_data_home)
            if xdg_data_home and Path(xdg_data_home).is_absolute()
            else Path.home() / ".local" / "share"
        )
    return (data_home / "project-brain" / "project-brain.db").expanduser().resolve()


def _read(path: Path, sql: str, params: Mapping[str, object]) -> list[tuple]:
    """The rows of one query, on a connection that cannot write. A connection per look, closed
    again: nothing stays open that could hold the file's write-ahead log back."""
    uri = f"{path.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=BUSY_SECONDS)) as db:
        return db.execute(sql, params).fetchall()


def prompted_since(path: Path, agent: str, session_id: str, since: datetime) -> bool:
    """Whether the person wrote in this chat after ``since``: the prompt hook saw a message."""
    rows = _read(
        path,
        "SELECT 1 FROM agent_session_events WHERE agent = :agent AND session_id = :chat"
        " AND source = 'prompt' AND created_at > :since LIMIT 1",
        {"agent": agent, "chat": session_id, "since": stamp(since)},
    )
    return bool(rows)


def has_open(path: Path, agent: str, session_id: str) -> bool:
    """Whether this chat has a question or report waiting for the person (see OPEN)."""
    found = _read(path, SESSION_TASK, {"agent": agent, "chat": session_id})
    task = found[0][0] if found else None
    return bool(_read(path, OPEN, {"chat": session_id, "task": task}))


def deliverable_ids(path: Path, session_id: str, now: datetime) -> list[str]:
    """The ids of the decisions waiting to be handed to this chat (see DELIVERABLE)."""
    rows = _read(path, DELIVERABLE, {"chat": session_id, "since": stamp(now - DELIVERY_WINDOW)})
    return [row[0] for row in rows]


def newer_waiter(path: Path, agent: str, session_id: str, mine: int) -> bool:
    """Whether another Stop hook began waiting for this chat after the one that wrote ``mine``."""
    rows = _read(
        path,
        "SELECT 1 FROM agent_session_events WHERE agent = :agent AND session_id = :chat"
        " AND source = 'waiting' AND id > :mine LIMIT 1",
        {"agent": agent, "chat": session_id, "mine": mine},
    )
    return bool(rows)


def codex_command(path: Path) -> str | None:
    """The command for Codex the person set in Settings, Agents (the ``codex_command`` setting,
    stored as JSON text), or None when there is none."""
    rows = _read(path, "SELECT value FROM app_settings WHERE key = 'codex_command'", {})
    try:
        value = json.loads(rows[0][0]) if rows and rows[0][0] is not None else None
    except ValueError:
        return None
    if not isinstance(value, str):
        return None
    return value.strip() or None


def release_ids(path: Path, ids: list[str]) -> int:
    """Give decisions back that a delivery claimed and could not hand over: ``delivered_at``
    empty again, so the next waiter or the prompt hook hands them over. Only decisions that are
    still ones (answered, sent back or accepted): a review the person decided again since has its
    own state. Returns how many were given back."""
    if not ids:
        return 0
    marks = ", ".join("?" for _ in ids)
    with closing(sqlite3.connect(str(path), timeout=BUSY_SECONDS)) as db:
        with db:
            done = db.execute(
                f"UPDATE task_reviews SET delivered_at = NULL WHERE id IN ({marks})"  # noqa: S608
                " AND delivered_at IS NOT NULL AND status IN ('answered', 'rejected', 'accepted')",
                ids,
            )
    return done.rowcount


def register(path: Path, agent: str, session_id: str, at: datetime) -> int:
    """Note that a Stop hook waits for this chat, and drop the notes of the waiters before it.
    Only ids and a time are stored. The row is not a task, a claim or a new session: nothing that
    reads ``agent_session_events`` for those looks at source ``waiting``."""
    with closing(sqlite3.connect(str(path), timeout=BUSY_SECONDS)) as db:
        try:
            db.execute("PRAGMA journal_mode=WAL")  # as db/session.py: the app shares this file
        except sqlite3.Error:
            pass
        with db:
            mine = db.execute(
                "INSERT INTO agent_session_events (agent, session_id, source, created_at)"
                " VALUES (?, ?, ?, ?)",
                (agent, session_id, WAITING, stamp(at)),
            ).lastrowid
            db.execute(
                "DELETE FROM agent_session_events WHERE agent = ? AND session_id = ?"
                " AND source = ? AND id < ?",
                (agent, session_id, WAITING, mine),
            )
    return mine


# ---- what needs Project Moah itself ------------------------------------------------------


def write_stderr(text: str) -> None:
    """The message, on standard error and flushed: what Claude Code shows the chat on exit 2."""
    stream = sys.stderr
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")  # a Windows pipe would use the ANSI code page
    stream.write(text.rstrip("\n") + "\n")
    stream.flush()


def write_stdout(text: str) -> None:
    """The message, on standard output and flushed (``--hook wait --print``, for a shell)."""
    stream = sys.stdout
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")
    stream.write(text.rstrip("\n") + "\n")
    stream.flush()


def _deliver(session_id: str, now: datetime, write: Write) -> bool:
    """Claim and hand over the chat's decisions, with Project Moah loaded for just this."""
    from app.core.config import get_database_url
    from app.db.session import make_engine, make_session_factory
    from app.services.chat_delivery import deliver

    engine = make_engine(get_database_url())
    try:
        with make_session_factory(engine)() as session:
            return deliver(session, session_id, write, now)
    finally:
        engine.dispose()


def log_error(message: str, detail: str = "") -> None:
    """Into the error log Settings shows. Never raises: it must not turn a failure into noise."""
    try:
        from app.core import error_log

        error_log.write("mcp", message, detail)
    except Exception:  # noqa: BLE001 - a hook that fails to say so still ends quietly
        pass


# ---- the parent -------------------------------------------------------------------------

SYNCHRONIZE = 0x00100000  # the right to wait for a process
WAIT_TIMEOUT = 0x102  # WaitForSingleObject's answer for a process that still runs
ERROR_ACCESS_DENIED = 5  # OpenProcess for a process that exists but is not ours to open
_windows_api: tuple | None = None


def _kernel32() -> tuple:
    """Windows' process functions, and the way to ask what went wrong (standard library only)."""
    global _windows_api
    if _windows_api is None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        _windows_api = (kernel32, ctypes.get_last_error)
    return _windows_api


def process_alive(pid: int, api: tuple | None = None) -> bool:
    """Whether the process with this id still runs, for Windows, where a process's parent id
    stays what it was when the parent ends. A handle that can only wait is opened, and waiting
    for it for no time at all says whether the process has ended. ``api`` is (kernel32, the
    function that gives the last error): tests hand in a fake one."""
    kernel32, last_error = api or _kernel32()
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return last_error() == ERROR_ACCESS_DENIED  # there, but not ours to open: still running
    try:
        return kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(handle)


# ---- the hooks ---------------------------------------------------------------------------


class Run(NamedTuple):
    """What the hooks read the world through: the clock, the sleep and the callbacks, so tests
    can run a whole day of waiting in no time. The defaults are the real ones. (Not a dataclass:
    that module alone costs a waiter 2 MB, for hours.)"""

    environ: Mapping[str, str] | None = None
    clock: Callable[[], datetime] = _now
    sleep: Callable[[float], None] = time.sleep
    getppid: Callable[[], int] = os.getppid
    alive: Callable[[int], bool] = process_alive
    windows: bool = sys.platform == "win32"
    write: Write = write_stderr
    deliver: Deliver = _deliver
    settle: float = SETTLE
    grace: float = GRACE
    poll: float = POLL
    limit: timedelta = WAIT_LIMIT
    show: Write = write_stdout  # ``--print``: what the Flatpak's shell line reads
    queue_timeout: float = QUEUE_TIMEOUT
    frozen: bool = bool(getattr(sys, "frozen", False))


def gone(parent: int, run: Run) -> bool:
    """Whether the process that started this hook, the agent, has ended. Its id changes when it
    does (the hook is given to another process), except on Windows: there it is asked for."""
    if run.windows:
        return not run.alive(parent)
    return run.getppid() != parent


def before_loading(argv: list[str], run: Run | None = None) -> int | None:
    """What a hook command can settle before the rest of Project Moah loads: its exit code, or
    None when the command goes on. The entry points (app/mcp/__main__.py, desktop_server.py)
    call this first.

    ``--hook wait`` and ``--hook release`` are the whole command (``handle``, ``release_hook``).
    A stop hook for a turn that did not end on a question, and a tool hook for a call that is none
    of Moah's, end here with 0; Codex's stop hook first starts its waiter when its chat has
    something open in Review (codex_waiter.after_stop). A stop hook with ``--settle`` waits first,
    and ends with 0 too when the person wrote meanwhile. Only a delivery returns 2 (``handle``)."""
    kind = hook_kind(argv)
    if kind == "wait":
        return handle(argv, run)
    if kind == "release":
        return release_hook(argv, run)
    if nothing_to_record(argv):
        if kind == "stop" and hook_agent(argv) == "codex":
            from app.services.codex_waiter import after_stop

            after_stop("codex", valid_id(read_hook_input().get("session_id")), run or Run())
        return 0
    if hook_kind(argv) == "stop" and "--settle" in argv:
        try:
            if _person_wrote(argv, run or Run()):
                return 0
        except Exception:  # noqa: BLE001 - not knowing, the hook records, as it always did
            pass
    return None


def _person_wrote(argv: list[str], run: Run) -> bool:
    """Wait SETTLE seconds, then say whether the person wrote in this chat in that time: the
    prompt hook saw a message (a PROMPT event) after this hook started."""
    started = run.clock()
    run.sleep(run.settle)
    session_id = valid_id(read_hook_input().get("session_id"))
    path = database_file(run.environ)
    if session_id is None or path is None or not path.is_file():
        return False
    try:
        return prompted_since(path, hook_agent(argv), session_id, started)
    except sqlite3.Error:
        return False


def release_hook(argv: list[str], run: Run | None = None) -> int:
    """``--hook release --ids "<ids>"``: give back decisions that a delivery claimed and could
    not hand over (the Flatpak's shell line, when ``codex queue`` failed). Always 0."""
    run = run or Run()
    try:
        path = database_file(run.environ)
        found = (option_value(argv, "--ids") or "").replace(",", " ").split()
        ids = [item for item in found if valid_id(item)][:RELEASE_LIMIT]
        if path is not None and path.is_file():
            release_ids(path, ids)
    except Exception as error:  # noqa: BLE001 - a hook that could not say so still ends quietly
        log_error(f"release hook: {type(error).__name__}", traceback.format_exc())
    return 0


def handle(argv: list[str], run: Run | None = None) -> int:
    """``--hook wait`` (see the module text). Returns the hook's exit code: 2 only after a
    decision was written to ``run.write``, else 0, whatever fails. Claude Code's waiter wakes
    its chat that way; Codex's (see codex_waiter) never returns 2. Any other agent's waiter
    ends at once."""
    if hook_agent(argv) not in ("claude", "codex"):
        return 0
    try:
        return _wait(run or Run(), argv)
    except sqlite3.OperationalError as error:
        if "no such" not in str(error):  # a database from before this version has no reviews
            log_error("wait hook: OperationalError", traceback.format_exc())
        return 0
    except Exception as error:  # noqa: BLE001 - never exit 2 on an error: that wakes the chat
        log_error(f"wait hook: {type(error).__name__}", traceback.format_exc())
        return 0


def _wait(run: Run, argv: list[str]) -> int:
    agent = hook_agent(argv)
    codex = agent == "codex"
    started = run.clock()
    parent = 0 if codex else run.getppid()  # Codex's waiter is detached: no parent to watch
    hook_input = read_hook_input()
    # Codex's detached waiter has no input of its own: its Stop hook gives it the chat.
    session_id = valid_id(hook_input.get("session_id")) or valid_id(
        option_value(argv, "--session-id")
    )
    path = database_file(run.environ)
    if session_id is None or path is None:
        return 0
    # The record hook writes the question the turn ended on in parallel, so give it its time.
    # Without one, only a late stamp can still open something (see the module text). Codex's
    # Stop hook recorded before it started this waiter, and its tool hook is a synchronous one:
    # nothing is late.
    asked = question_parts(stop_message(hook_input)) is not None
    patience = 0.0 if codex else (run.grace if asked else run.settle)
    deadline = started + run.limit
    mine: int | None = None
    misses = 0
    while True:
        now = run.clock()
        if now >= deadline or (not codex and gone(parent, run)):
            return 0
        if mine is not None and newer_waiter(path, agent, session_id, mine):
            return 0
        here = path.is_file()  # the record hook may be about to make the database
        if here and deliverable_ids(path, session_id, now):
            if codex:
                if _hand_to_codex(run, argv, path, session_id, now) != "nothing":
                    return 0  # queued, printed or failed: this waiter's work is done
            elif gone(parent, run):
                return 0  # the chat is gone: nobody would read it
            elif run.deliver(session_id, now, run.write):
                return 2
            misses += 1
            if misses >= MAX_MISSES:
                log_error(
                    "wait hook: a decision was found but could not be claimed",
                    f"{MAX_MISSES} looks in a row, chat {session_id}",
                )
                return 0
        else:
            misses = 0
            if here and has_open(path, agent, session_id):
                if mine is None:
                    mine = register(path, agent, session_id, now)
            elif (now - started).total_seconds() >= patience:
                return 0
            elif not asked:
                run.sleep(run.settle)  # one more look, once a late stamp has had its time
                continue
        run.sleep(run.poll)


def _hand_to_codex(run: Run, argv: list[str], path: Path, session_id: str, now: datetime) -> str:
    """Hand a Codex chat its decisions: ``queue`` them with ``codex queue``, or, with
    ``--print``, print them for the shell line that runs Codex outside a sandbox (see
    codex_waiter). "sent" when a message went out, "nothing" when another process claimed the
    decisions first, "failed" when it could not be done: the claim is given back then (the prompt
    hook hands the decisions over at the person's next message) and the reason is logged."""
    from app.services import codex_waiter

    if "--print" in argv:

        def write(text: str) -> None:
            codex_waiter.print_message(session_id, text, run.show)

    else:
        # Found before anything is claimed, so a computer that cannot queue leaves the decision
        # where the prompt hook will find it, instead of claiming it and giving it back.
        environ = os.environ if run.environ is None else run.environ
        found = codex_waiter.resolve_codex(
            codex_command(path), environ, windows=run.windows, machine=""
        )
        if found.command is None:
            log_error("wait hook: Codex cannot be woken from here", found.problem)
            return "failed"
        command = found.command

        def write(text: str) -> None:
            codex_waiter.queue(command, session_id, codex_waiter.fit_message(text), run)

    try:
        return "sent" if run.deliver(session_id, now, write) else "nothing"
    except codex_waiter.QueueError as error:  # deliver gave the claim back
        log_error(f"wait hook: {error}", error.detail)
        return "failed"

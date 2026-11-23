"""What the person decides in Review reaches a Codex session: the detached waiter.

Codex runs its hooks one after the other and waits for each: a hook that waits for the person
would hold the session up, and a background hook that ends never starts a turn. What does start a
turn in an idle Codex session, open or closed, is ``codex queue --thread <session> --message
<text>``. So the pieces are:

1. Codex's Stop hook (``--agent codex --hook stop``) records the turn as it always did, then, when
   the chat has something open in Review or a decision waiting, starts ONE detached
   ``--agent codex --hook wait --session-id <id>`` and ends at once (``after_stop``,
   ``start_waiter``). It does so only where Moah is not sandboxed: a Flatpak cannot run anything
   outside its sandbox, so there the hook line's own shell does it (``flatpak_stop_line``).
2. The waiter (chat_wait.handle, which this module serves) looks once at once, then every POLL
   seconds. When the person decided, it claims the decision (``delivered_at``) and runs ``codex
   queue`` (``queue``, with the program ``resolve_codex`` found). The queued message starts a turn
   in the session, where the prompt hook knows it by its first line (chat_delivery.DELIVERY_MARKER)
   and never takes it for the person's reply. When the queue fails, the claim is given back and
   the prompt hook hands the decision over at the person's next message (its stdout is added to
   Codex's context). Unlike Claude's waiter it does not look at its parent: it is detached on
   purpose, and the queue works for a session that was closed (delivered when it is resumed).

The spawn rule is the simplest correct one: every Codex Stop that finds the chat with something
open (or a decision waiting) starts a waiter, and the newest wins. A waiter that has something to
wait for notes it (chat_wait.register, source ``waiting``), and an older waiter for the same chat
ends at its next look when it sees a newer note. Waiters never pile up: each ends within POLL
seconds of a newer one noting itself.

Standard library only until a decision is found, like chat_wait: this is imported by every Codex
Stop hook. Nothing here goes online: ``codex queue`` talks to the Codex on this computer.

The Flatpak's Stop line (step 5 of the plan writes it into Codex's hooks; see
``flatpak_stop_line``), for ``<moah>`` = ``flatpak run --command=project-moah-mcp <app id>``:

    d=$(cat); printf %s "$d" | <moah> --agent codex --hook stop >/dev/null 2>&1;
    if command -v setsid >/dev/null 2>&1; then s=setsid; else s=nohup; fi;
    { printf %s "$d" | $s sh -c '<moah> --agent codex --hook wait --print | { read -r t &&
    read -r i && m=$(cat) && { codex queue --thread "$t" --message "$m" || <moah> --agent codex
    --hook release --ids "$i"; }; }'; } >/dev/null 2>&1 </dev/null &

(one line in the real thing). Why it is built like that:

- Codex's JSON is kept in a variable and fed to both commands. The shell never has to read a
  session id out of JSON (no jq, no sed): ``--hook wait`` reads it from its standard input as the
  Claude waiter does. ``--hook stop`` prints nothing and the waiter's output goes into a pipe, so
  nothing reaches Codex: all of the line's own output goes to /dev/null.
- ``--print`` makes the waiter claim the decision and print three things instead of queueing it
  itself (line 1 the thread id, line 2 the ids of the decisions, the rest the message), because
  the sandbox cannot run ``codex``. The shell reads them, runs ``codex queue`` on the host and,
  when that fails, gives the decisions back with ``--hook release``. Nothing printed: nothing was
  claimed, and the shell ends there.
- The waiter, the reader and ``codex queue`` run in one new session (``setsid``; ``nohup`` where
  there is none) with every stream on /dev/null, so Codex ending the hook (or its process group)
  neither waits for them nor kills the reader after the waiter claimed a decision. The line ends
  with ``&``: its exit code is 0 and it returns as soon as the stop hook has recorded.
- The command and the program names are quoted with shlex, twice: once for the inner script and
  once for the shell that runs it, so the line is right for any launcher.
"""

from __future__ import annotations

import os
import shlex
import signal
import sys
import traceback
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

from app.services.chat_wait import Run, database_file, deliverable_ids, has_open, log_error

MESSAGE_LIMIT = 8000  # characters of one queued message: Windows takes 32K in a command line
CUT_NOTE = "(cut: the rest is in Moah)"
FLATPAK_INFO = Path("/.flatpak-info")
ERROR_TEXT = 300  # characters of what ``codex queue`` said that go to the error log

# Windows' process creation flags. The subprocess module has them on Windows only.
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

# The native program the npm package of Codex ships: (package, target triple, file name), as its
# bin/codex.js picks them (@openai/codex 0.163.0). The Linux one was checked against the package;
# the Windows ones are read off the same script, not run on Windows.
NATIVE = {
    ("win32", "x64"): ("codex-win32-x64", "x86_64-pc-windows-msvc", "codex.exe"),
    ("win32", "arm64"): ("codex-win32-arm64", "aarch64-pc-windows-msvc", "codex.exe"),
    ("linux", "x64"): ("codex-linux-x64", "x86_64-unknown-linux-musl", "codex"),
    ("linux", "arm64"): ("codex-linux-arm64", "aarch64-unknown-linux-musl", "codex"),
}
PROGRAMS = (".exe", ".com")  # what Windows runs without a shell
SCRIPTS = (".cmd", ".bat")  # what Windows runs through cmd.exe, which re-reads & | ^ % in a word


class QueueError(RuntimeError):
    """``codex queue`` did not take the message. ``detail`` is what the program said."""

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


# ---- starting the waiter -----------------------------------------------------------------


def sandboxed(info: Path | None = None) -> bool:
    """Whether Project Moah runs inside a Flatpak, which cannot start anything outside it (as
    services/git.py and system.py ask it)."""
    return (info or FLATPAK_INFO).exists()


def launcher(orig_argv: Sequence[str] | None = None, executable: str | None = None) -> list[str]:
    """The words that started this command, up to its own options: what the agent's hook line
    wrote before ``--agent``/``--hook``. A frozen executable (``project-brain-backend --mcp``),
    ``python -m app.mcp`` and the desktop service's ``--mcp`` form all come out right, and so
    does an interpreter's own options. The first word is this process's own program, because
    argv[0] may be a bare name that a detached process with another PATH could not find.
    Empty when the command line does not say."""
    argv = list(sys.orig_argv if orig_argv is None else orig_argv)
    cut = next(
        (
            index
            for index, word in enumerate(argv)
            if word in ("--agent", "--hook") or word.startswith(("--agent=", "--hook="))
        ),
        0,
    )
    if cut == 0:
        return []
    return [executable or sys.executable, *argv[1:cut]]


def child_environment(environ: Mapping[str, str], frozen: bool) -> dict[str, str]:
    """The environment for a program this one starts. A frozen executable's own markers and
    library path would make the next copy of it, or Codex, run against the wrong files (the same
    care as system.open_app_in_tray takes)."""
    env = dict(environ)
    if not frozen:
        return env
    for name in [n for n in env if n.startswith(("_PYI_", "_MEIPASS"))]:
        del env[name]
    env.pop("ELECTRON_RUN_AS_NODE", None)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    original = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if original is not None:
        env["LD_LIBRARY_PATH"] = original
    else:
        env.pop("LD_LIBRARY_PATH", None)  # it was not set: what is there is the bundle's own
    return env


def detach_options(windows: bool) -> list[dict]:
    """What ``Popen`` needs to start a process that outlives the hook, one set per try. POSIX: a
    session of its own. Windows: no console, a process group of its own, and, first, out of the
    job the agent may have put its hooks in (a job can refuse that, and CreateProcess then
    fails: the second try leaves it out, and a job that kills its processes at the end takes the
    waiter with it, which the prompt hook makes up for)."""
    if not windows:
        return [{"start_new_session": True}]
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    return [
        {"creationflags": flags | CREATE_BREAKAWAY_FROM_JOB},
        {"creationflags": flags},
    ]


def waiter_command(
    session_id: str,
    orig_argv: Sequence[str] | None = None,
    executable: str | None = None,
    frozen: bool | None = None,
) -> list[str]:
    """The command line of the waiter for this chat: this command's own launcher, then
    ``--agent codex --hook wait --session-id <id>``. When the command line does not say how this
    started (an embedded interpreter that does not keep it), the way an install starts its MCP
    server is used: the executable's ``--mcp`` when frozen, else ``python -m app.mcp`` (as
    system.agent_launch has them)."""
    program = executable or sys.executable
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    words = launcher(orig_argv, program) or [program, *(["--mcp"] if frozen else ["-m", "app.mcp"])]
    return [*words, "--agent", "codex", "--hook", "wait", "--session-id", session_id]


def start_waiter(command: list[str], run: Run) -> bool:
    """Start the command detached from this process and from Codex's pipes (standard streams on
    the null device, so Codex is not kept waiting for output that never ends). True when it
    started. The folder it starts in is a neutral one on Windows, where a running process keeps
    its folder from being renamed or deleted: the project's folder is the agent's."""
    import subprocess

    environ = os.environ if run.environ is None else run.environ
    env = child_environment(environ, run.frozen)
    extra = {}
    if run.windows and os.path.isdir(home := os.path.expanduser("~")):
        extra["cwd"] = home
    for options in detach_options(run.windows):
        try:
            subprocess.Popen(  # noqa: S603 - a fixed argument list, no shell
                command,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                **extra,
                **options,
            )
            return True
        except OSError:
            continue
    return False


def after_stop(agent: str, session_id: str | None, run: Run | None = None) -> bool:
    """A Codex turn ended and was recorded: start the waiter when the chat has something open
    in Review or a decision to hand over, unless Moah is sandboxed. True when one started. Never
    raises: a waiter that did not start costs only the prompt hook's hand-over at the person's
    next message."""
    run = run or Run()
    if agent != "codex" or session_id is None or sandboxed():
        return False
    try:
        path = database_file(run.environ)
        if path is None or not path.is_file():
            return False
        now = run.clock()
        if not deliverable_ids(path, session_id, now) and not has_open(path, agent, session_id):
            return False
        if not start_waiter(waiter_command(session_id, frozen=run.frozen), run):
            log_error("codex waiter: not started", "the process could not be created")
            return False
        return True
    except Exception as error:  # noqa: BLE001 - the Stop hook never fails the agent
        if "no such" not in str(error):  # a database from before this version has no reviews
            log_error(f"codex waiter: {type(error).__name__}", traceback.format_exc())
        return False


# ---- finding Codex -----------------------------------------------------------------------


class Found(NamedTuple):
    """A program to run: its command, or why there is none."""

    command: list[str] | None
    problem: str = ""


def split_command(text: str, windows: bool) -> list[str]:
    """The words of the setting for Codex's command (Settings, Agents): the whole text when it
    names a file (a path with spaces, typed as it is; on Windows also without ``.exe``), else its
    words, quotes removed."""
    text = text.strip()
    if text and any(
        os.path.isfile(text + ending) for ending in ("", *(PROGRAMS if windows else ()))
    ):
        return [text]
    try:
        words = shlex.split(text, posix=not windows)
    except ValueError:
        return []
    return [w[1:-1] if len(w) > 1 and w[0] == w[-1] and w[0] in "\"'" else w for w in words]


def native_program(folder: Path, windows: bool, machine: str) -> Path | None:
    """The program the npm package of Codex ships, found from the folder that holds its Windows
    shim (``codex.cmd``, next to the package's ``node_modules``, or inside a ``node_modules/.bin``).
    The package keeps it in a sibling package of the platform (@openai/codex-win32-x64), beside
    the script's own package or inside it, and as a last resort in the script's own ``vendor``:
    the places bin/codex.js looks in."""
    system = "win32" if windows else "linux"
    arch = "arm64" if machine.lower() in ("arm64", "aarch64") else "x64"
    package, triple, name = NATIVE[system, arch]
    roots = [folder / "node_modules"]
    if folder.name == ".bin":
        roots.append(folder.parent)
    for root in roots:
        scope = root / "@openai"
        for base in (scope / package, scope / "codex" / "node_modules" / "@openai" / package):
            if (found := base / "vendor" / triple / "bin" / name).is_file():
                return found
        if (found := scope / "codex" / "vendor" / triple / "bin" / name).is_file():
            return found
    return None


def resolve_codex(
    configured: str | None,
    environ: Mapping[str, str],
    *,
    windows: bool,
    machine: str = "",
) -> Found:
    """The program that can take ``queue`` for Codex: the Settings command, else ``codex`` on
    PATH. On Windows only a real program counts (.exe, .com). The message goes on the command
    line, and a script (npm's ``codex.cmd``) runs through cmd.exe, which reads & | ^ % in it as
    commands: the person's words must never pass through one. A script shim gives the program
    its package ships beside it, if that is there; else there is no program, and the caller says
    why."""
    words = split_command(configured or "codex", windows)
    if not words:
        return Found(None, "the command for Codex in Settings is empty")
    name, extra = words[0], words[1:]
    where = Path(name)
    if where.name != name:  # it names a folder too: a path
        folders, stem = [where.parent], where.name
    else:
        folders = [Path(f) for f in environ.get("PATH", "").split(os.pathsep) if f]
        stem = name
    if not windows:
        for folder in folders:
            program = folder / stem
            if program.is_file() and os.access(program, os.X_OK):
                return Found([str(program), *extra])
        return Found(None, f"{stem} was not found")
    suffix = Path(stem).suffix.lower()
    known = (*PROGRAMS, *SCRIPTS)
    names = [stem] if suffix in known else [stem + ending for ending in known]
    machine = machine or environ.get("PROCESSOR_ARCHITEW6432", "")
    machine = machine or environ.get("PROCESSOR_ARCHITECTURE", "")
    shim = None
    for folder in folders:
        for candidate in names:
            program = folder / candidate
            if not program.is_file():
                continue
            if program.suffix.lower() in PROGRAMS:
                return Found([str(program), *extra])
            shim = shim or program
            if native := native_program(folder, True, machine):
                return Found([str(native), *extra])
    if shim is not None:
        return Found(
            None,
            f"only a script ({shim}) was found, and Windows would run the person's words "
            "through cmd.exe with it: set the command for Codex in Settings to its codex.exe",
        )
    return Found(None, f"{stem} was not found")


# ---- the message -------------------------------------------------------------------------


def fit_message(text: str, limit: int = MESSAGE_LIMIT) -> str:
    """The message within ``limit`` characters, as a command line takes it. What is too long is
    cut from the middle: the first line (the marker the prompt hook knows it by) and the last
    (the ids of the decisions) stay, and a note says the rest is in Moah."""
    text = text.rstrip()
    if len(text) <= limit:
        return text
    lines = text.split("\n")
    head, tail = lines[0], lines[-1]
    middle = "\n".join(lines[1:-1]).strip()
    room = max(limit - len(head) - len(tail) - len(CUT_NOTE) - 6, 0)
    return f"{head}\n\n{middle[:room].rstrip()}… {CUT_NOTE}\n\n{tail}"


def queue(
    command: list[str],
    thread: str,
    text: str,
    run: Run,
) -> None:
    """``codex queue --thread <thread> --message <text>``, for at most ``run.queue_timeout``
    seconds. Raises QueueError when the program cannot start, does not finish in time or ends
    with an error. The text goes in as one argument and is never put through a shell (the
    program is a real one, ``resolve_codex``)."""
    import subprocess

    environ = os.environ if run.environ is None else run.environ
    options: dict = (
        {"creationflags": CREATE_NO_WINDOW} if run.windows else {"start_new_session": True}
    )
    try:
        process = subprocess.Popen(  # noqa: S603 - a fixed argument list, no shell
            [*command, "queue", "--thread", thread, "--message", text],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=child_environment(environ, run.frozen),
            text=True,
            encoding="utf-8",
            errors="replace",
            **options,
        )
    except OSError as error:
        raise QueueError(
            "codex could not be started", f"{type(error).__name__}: {error}"
        ) from error
    try:
        _, said = process.communicate(timeout=run.queue_timeout)
    except subprocess.TimeoutExpired:
        _end(process, run.windows)
        raise QueueError(f"codex queue did not finish in {run.queue_timeout:g} seconds") from None
    if process.returncode != 0:
        raise QueueError(f"codex queue ended with code {process.returncode}", _said(said))


def _said(text: str) -> str:
    """What a failed ``codex queue`` reported, short enough for the error log: its error line
    (the program also prints warnings and a stack trace)."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    line = next((item for item in lines if item.startswith("Error")), lines[0] if lines else "")
    return line[:ERROR_TEXT]


def _end(process, windows: bool) -> None:
    """Stop a ``codex queue`` that took too long, with what it started (the npm script starts the
    program): on POSIX its whole session."""
    try:
        if windows:
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        process.kill()
    process.communicate()


def print_message(thread: str, text: str, write: Callable[[str], None]) -> None:
    """What ``--print`` writes for the Flatpak's shell line: the thread id, the ids of the
    decisions (space between), and the message, one after the other, line by line."""
    from app.services.chat_delivery import delivery_ids

    text = fit_message(text)
    write(f"{thread}\n{' '.join(delivery_ids(text))}\n{text}")


# ---- the Flatpak's hook line -------------------------------------------------------------


def flatpak_stop_line(command: Sequence[str], codex: str = "codex") -> str:
    """The shell line for Codex's Stop hook in a Flatpak install (see the module text for what
    it does and why). ``command`` is how Codex starts Moah there (``flatpak run
    --command=project-moah-mcp <app id>``), ``codex`` the program that queues, on the host. It
    prints nothing, and returns as soon as the stop hook has recorded the turn."""
    moah = shlex.join(command)
    inner = (
        f"{moah} --agent codex --hook wait --print"
        " | { read -r t && read -r i && m=$(cat) && { "
        f'{shlex.quote(codex)} queue --thread "$t" --message "$m"'
        f' || {moah} --agent codex --hook release --ids "$i"; }}; }}'
    )
    return (
        f'd=$(cat); printf %s "$d" | {moah} --agent codex --hook stop >/dev/null 2>&1; '
        "if command -v setsid >/dev/null 2>&1; then s=setsid; else s=nohup; fi; "
        f'{{ printf %s "$d" | $s sh -c {shlex.quote(inner)}; }} >/dev/null 2>&1 </dev/null &'
    )

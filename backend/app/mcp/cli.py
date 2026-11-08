"""The `project-moah-mcp` command: the MCP server over stdio, the session brief (`--brief`), or
an agent hook (`--hook stop` / `--hook prompt`, services/chat_questions.py).

Kept apart from server.py so the start-up hook, which runs at every agent session start, clear
and compaction, loads only what the brief needs: not the MCP library, which takes about as long
to load as the rest of the brief together.
"""

from __future__ import annotations

import argparse
import os
import sys

from app.core import error_log
from app.core.config import get_database_url
from app.db.migrate import upgrade_database
from app.db.session import make_engine, make_session_factory
from app.services.builds import register_build
from app.services.update_check import take_daily_check


def with_update_check(session, brief: str) -> str:
    """The brief, plus the day's update check if it is on and has not been given today."""
    try:
        check = take_daily_check(session)
    except Exception:  # noqa: BLE001 - a busy database must never cost the agent its rules
        session.rollback()
        return brief
    return f"{brief}\n\n{check}" if check else brief


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="project-moah-mcp", description="Project Moah MCP server (stdio)"
    )
    parser.add_argument(
        "--agent", default="agent", help="who is connecting: codex, claude, or another name"
    )
    parser.add_argument(
        "--project", default=None, help="project slug, name or id to use when none is given"
    )
    parser.add_argument(
        "--brief",
        action="store_true",
        help="print the session brief for --cwd and exit (for agent start-up hooks)",
    )
    parser.add_argument(
        "--hook",
        choices=("stop", "prompt"),
        default=None,
        help="run an agent hook and exit: stop (the agent ended its turn) or prompt (the person "
        "wrote); reads the hook's JSON on standard input and prints nothing",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="the agent's session id, for installs where the agent's environment does not reach "
        "this server (a Flatpak started from a container); Connect adds it",
    )
    parser.add_argument(
        "--cwd",
        default=None,
        help="working folder used to find the project (--brief: defaults to Claude Code's "
        "project folder, then the current folder)",
    )
    return parser.parse_args(argv)


def print_brief(session, args: argparse.Namespace) -> None:
    from app.mcp.projects import ProjectChoiceError, resolve_project
    from app.services.agent_sessions import read_hook_input, record_start
    from app.services.agent_sync import sync_quietly
    from app.services.brief import build_brief
    from app.services.context import mark_context_reset

    sync_quietly(session)
    # A session just started, was cleared or was compacted: packs sent before are no longer in
    # its context, so running MCP servers send the next one in full.
    mark_context_reset(session)
    # Hooks on Windows can't pass the folder portably: cmd.exe and Git Bash spell variables
    # differently, so read Claude Code's own variable here instead.
    cwd = args.cwd or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    try:
        found, _ = resolve_project(session, args.project, cwd)
        note = hint = None
    except ProjectChoiceError as error:
        found, note, hint = None, str(error), error.hint
    # Claude Code hands the hook its session id: remember it with the project, so token use in
    # that session's log can be matched to its tasks.
    hook_agent = "claude" if args.agent == "agent" else args.agent.strip().casefold()
    try:
        record_start(session, hook_agent, read_hook_input(), found.id if found else None)
    except Exception:  # noqa: BLE001 - the brief matters more than the record
        session.rollback()
    print(with_update_check(session, build_brief(session, found, note, hint)), flush=True)


def run_hook(session, args: argparse.Namespace) -> None:
    """One agent hook. Never fails the agent: whatever goes wrong, its turn goes on as before."""
    from app.services.agent_sessions import read_hook_input
    from app.services.chat_questions import HOOKS

    agent = "claude" if args.agent == "agent" else args.agent.strip().casefold()
    try:
        HOOKS[args.hook](session, agent, read_hook_input())
    except Exception as error:  # noqa: BLE001 - a hook must never stop the agent or the person
        session.rollback()
        print(f"Project Moah {args.hook} hook: {error}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    url = get_database_url()
    error_log.install("mcp")  # the start-up brief too: a failure there is otherwise silent
    upgrade_database(url)
    engine = make_engine(url)
    if args.hook:
        # Runs at every turn and every message: nothing else, and nothing on standard output,
        # which Claude Code would add to the person's message.
        try:
            with make_session_factory(engine)() as session:
                run_hook(session, args)
        finally:
            engine.dispose()
        return 0
    try:
        with make_session_factory(engine)() as session:
            register_build(session, installed=False)  # a new session may be a new build's first
    except Exception:  # noqa: BLE001 - never stop an agent's tools over this note
        pass
    if args.brief:
        # Hooks read the brief as UTF-8. A Windows pipe would use the ANSI code page and fail on
        # the first title it cannot encode, so the agent would start without its rules.
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        try:
            with make_session_factory(engine)() as session:
                print_brief(session, args)
        finally:
            engine.dispose()
        return 0
    from app.mcp.server import build_server
    from app.services.agent_sessions import SESSION_ENV

    if args.session_id:  # what Claude Code puts in the environment, when only arguments arrive
        os.environ[SESSION_ENV] = args.session_id

    try:
        # stdout belongs to the protocol; anything human-readable goes to stderr.
        print(f"Project Moah MCP server ready (agent: {args.agent})", file=sys.stderr, flush=True)
        build_server(
            make_session_factory(engine), agent=args.agent, default_project=args.project
        ).run("stdio")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

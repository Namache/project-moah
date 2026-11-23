"""The `project-moah-mcp` command: the MCP server over stdio, the session brief (`--brief`), or
an agent hook (`--hook stop` / `prompt` / `tool` / `wait` / `release`, services/chat_questions.py,
chat_wait.py, codex_waiter.py).

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
        choices=("stop", "prompt", "tool", "wait", "release"),
        default=None,
        help="run an agent hook and exit: stop (the agent ended its turn), prompt (the person "
        "wrote), tool (a Moah tool ran: PostToolUse), wait (the waiter for the person's "
        "decision in Review, services/chat_wait.py; Codex's is started by its stop hook, "
        "services/codex_waiter.py) or release (give decisions back that could not be handed "
        "over, with --ids); reads the hook's JSON on standard input and prints nothing, except "
        "what the person decided in Review for this chat (services/chat_delivery.py)",
    )
    parser.add_argument(
        "--settle",
        action="store_true",
        help="stop hook: wait a few seconds before recording, and record nothing when the person "
        "wrote in the chat meanwhile (only for the background hook line Connect writes: a "
        "synchronous one would hold up the agent's turn)",
    )
    parser.add_argument(
        "--deliver",
        action="store_true",
        help="Claude Code's prompt hook: hand the chat what the person decided in Review, and "
        "wake it with exit code 2 (only for the hook line Connect writes with asyncRewake: "
        "from a plain background hook that exit code is lost)",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        help="Codex's waiter (--hook wait): claim the decision and print it for a shell to queue "
        "(line 1 the thread id, line 2 the ids of the decisions, the rest the message) instead "
        "of running codex itself; for a Flatpak, which cannot run it (codex_waiter."
        "flatpak_stop_line)",
    )
    parser.add_argument(
        "--ids",
        default=None,
        help="--hook release: the ids of the decisions to give back, separated by spaces",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="the agent's session id, for installs where the agent's environment does not reach "
        "this server (a Flatpak started from a container) and for Codex's detached waiter, "
        "which has no input; Connect adds it to the server",
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


def run_hook(session, args: argparse.Namespace) -> int:
    """One agent hook. Never fails the agent: whatever goes wrong, its turn goes on as before.

    Returns the hook's exit code: 0, except 2 for the prompt hook that handed the chat a decision
    the person gave in Review (Claude Code wakes the chat on a background hook's exit 2, which is
    why nothing else, and no error, ever returns it)."""
    from app.services.agent_sessions import read_hook_input
    from app.services.chat_delivery import prompt_delivery
    from app.services.chat_questions import HOOKS
    from app.services.codex_waiter import after_stop
    from app.services.hook_text import valid_id

    agent = "claude" if args.agent == "agent" else args.agent.strip().casefold()
    code = 0
    try:
        hook_input = read_hook_input()
        HOOKS[args.hook](session, agent, hook_input)
        if args.hook == "prompt":
            code = prompt_delivery(session, agent, hook_input, wake=args.deliver)
        elif args.hook == "stop":
            # Codex cannot wait in a hook: once the turn is recorded, a detached waiter does.
            after_stop(agent, valid_id(hook_input.get("session_id")))
    except Exception as error:  # noqa: BLE001 - a hook must never stop the agent or the person
        session.rollback()
        print(f"Project Moah {args.hook} hook: {error}", file=sys.stderr)
    return code


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as end:
        # A command line that argparse refuses ends with exit code 2: for a hook that would wake
        # the chat with a usage message. Only a delivery may.
        if "--hook" in (sys.argv[1:] if argv is None else argv):
            return 0
        raise end
    if args.hook in ("wait", "release"):
        # Normally settled before this module loads (chat_wait.before_loading).
        from app.services.chat_wait import handle, release_hook

        words = sys.argv[1:] if argv is None else argv
        return handle(words) if args.hook == "wait" else release_hook(words)
    url = get_database_url()
    error_log.install("mcp")  # the start-up brief too: a failure there is otherwise silent
    upgrade_database(url)
    engine = make_engine(url)
    if args.hook:
        # Runs at every turn and every message: nothing else, and nothing on standard output,
        # which Claude Code would add to the person's message.
        try:
            with make_session_factory(engine)() as session:
                return run_hook(session, args)
        finally:
            engine.dispose()
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
    from app.services.agent_connect import connection_notice
    from app.services.agent_sessions import SESSION_ENV

    outdated = connection_notice(args.agent, args.session_id)
    if args.session_id:  # what Claude Code puts in the environment, when only arguments arrive
        os.environ[SESSION_ENV] = args.session_id

    try:
        # stdout belongs to the protocol; anything human-readable goes to stderr.
        print(f"Project Moah MCP server ready (agent: {args.agent})", file=sys.stderr, flush=True)
        build_server(
            make_session_factory(engine),
            agent=args.agent,
            default_project=args.project,
            connection_notice=outdated,
        ).run("stdio")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

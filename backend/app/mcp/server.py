"""The Project Moah MCP server (stdio). One small tool set for retrieving and recording work.

Rules this adapter keeps:
- Agents never silently change locked memory or complete tasks. Those become proposals.
- Every write is attributed to the agent named in the server's settings.
- A project is chosen explicitly, or from the working directory only when unambiguous.
- Errors say what to do next; no stack traces reach the agent.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from functools import wraps
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ImageContent, TextContent, ToolAnnotations
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker
from starlette.exceptions import HTTPException

from app.core import error_log
from app.mcp.cli import main  # noqa: F401 - old entry point
from app.mcp.kit import ToolKit
from app.mcp.linking import SessionPacks, SessionTask
from app.mcp.projects import ProjectChoiceError, resolve_project
from app.mcp.schemas import compact_tools
from app.mcp.tools import register_all
from app.models.project import GLOBAL_PROJECT_ID
from app.schemas.memory import HUMAN
from app.services.activity import acting_as
from app.services.agent_sessions import SessionTracker
from app.services.builds import UpdateWatch
from app.services.graph import TRAVERSABLE_STATUSES, Node
from app.services.proposals import actor_for
from app.services.shelves import ShelfService

# In the system prompt of every session, next to the brief, so it says only what a client
# without the start-up hook needs to get the brief. The brief itself says when to fetch more.
INSTRUCTIONS = """\
Project Moah is the person's shared memory for Claude Code and Codex: rules, decisions, tasks
and checkpoints for every project. At the start of a session, call brain_brief with your working
folder as cwd, unless its brief is already in your context, and follow it. Their earlier answers
are here, so check Moah (brain_context_pack or brain_search) before you ask them anything.
Writing records and checkpoints is part of the work and needs no permission. Global rules,
global decisions and locked records go to the person as proposals (brain_create_proposal). Each
request, however small, is a task of its own (brain_create_task in_progress unless one
covers it): hand it over with brain_submit_review when done, and ask with brain_ask_person when you stop for
an answer."""


def _message(error: Exception) -> str:
    if isinstance(error, HTTPException):
        text = str(error.detail)
        if error.status_code == 423:
            text += " Use brain_create_proposal to suggest the change for a person to review."
        return text
    if isinstance(error, ValidationError):
        first = error.errors()[0]
        return f"Invalid input ({'.'.join(map(str, first['loc']))}: {first['msg']})"
    if isinstance(error, ProjectChoiceError | ValueError):
        return str(error)
    return f"{type(error).__name__}: {error}"


def _unexpected(error: Exception) -> bool:
    """An error of the app itself, as opposed to a tool call the agent can correct."""
    if isinstance(error, HTTPException):
        return error.status_code >= 500
    return not isinstance(error, ValidationError | ProjectChoiceError | ValueError | ToolError)


CLAUDE_CODE = "claude-code"  # the name Claude Code gives MCP servers it starts


def build_server(
    session_factory: sessionmaker[Session],
    *,
    agent: str = "agent",
    default_project: str | None = None,
    connection_notice: str | None = None,
) -> MCPServer:
    """The MCP server. connection_notice, from services/agent_connect.py, goes with the first
    answer to Claude Code: how the agent refreshes a connection an older version set up."""
    if agent.strip().casefold() == HUMAN:
        raise ValueError("--agent cannot be 'human': agents are never recorded as a person.")
    server = MCPServer("project-moah", instructions=INSTRUCTIONS)
    actor = actor_for(agent)
    working = SessionTask()
    watch = UpdateWatch()
    untold = {"moah_connection": connection_notice} if connection_notice else {}
    client: dict[str, str] = {}  # the program on the other end, once it has said its name

    async def remember_client(ctx: Any, call_next: Any) -> Any:
        params = getattr(ctx.session, "client_params", None)
        if "name" not in client and params is not None and params.client_info is not None:
            client["name"] = params.client_info.name
        return await call_next(ctx)

    server.middleware.append(remember_client)
    sessions = SessionTracker(agent.strip().casefold())
    packs = SessionPacks()
    # Which project this session's brief covered, once brain_brief was called. Until then the
    # brief is the start-up hook's, for the folder the client started this server in.
    briefed: dict[str, str | None] = {}

    def folder_project(session: Session) -> str | None:
        """The project of the folder this server runs in, for adopting a session (see
        SessionTracker.adopt). Only looked up while the server has no session id."""
        if sessions.started is not None:
            return None
        try:
            return resolve_project(session, None, None, default_project)[0].id
        except ProjectChoiceError:  # no project for the folder: adopt nothing
            return None

    def tool(annotations: ToolAnnotations):
        """Register a tool that gets a session, attribution, and readable errors."""

        def decorate(fn: Callable[..., Any]):
            @wraps(fn)
            def run(*args: Any, **kwargs: Any) -> Any:
                working.tick()
                packs.tick()
                with session_factory() as session:
                    try:
                        if sessions.refresh(session, folder_project(session)):
                            working.clear()  # /clear started a new session: no task of its own
                            packs.clear()  # and none of the packs sent before are in its context
                            briefed.clear()  # and the start-up hook gave it a new brief
                        if (named := sessions.named_by_person(session)) is not None:
                            working.set(*named)  # the person's message named the task
                        with acting_as(actor, agent):
                            result = fn(session, *args, **kwargs)
                        sessions.record_tasks(session, working.tasks())
                        return with_notices(result, session)
                    except Exception as error:  # noqa: BLE001 - turned into a plain message
                        session.rollback()
                        if _unexpected(error):
                            error_log.write(
                                "mcp", f"{fn.__name__}: {_message(error)}", traceback.format_exc()
                            )
                        raise ToolError(_message(error)) from None

            # The session is injected, so it must not appear in the tool's schema.
            import inspect

            sig = inspect.signature(fn)
            run.__signature__ = sig.replace(parameters=list(sig.parameters.values())[1:])  # type: ignore[attr-defined]
            return server.tool(annotations=annotations)(run)

        return decorate

    def with_notices(result: Any, session: Session) -> Any:
        """Once per session each: 'restart me' on the first answer after a newer build appears,
        and 'refresh my connection' on the first answer of all."""
        if (watch.told and not untold) or not isinstance(result, str | dict | list):
            return result
        if isinstance(result, list) and not (
            result and all(isinstance(part, TextContent | ImageContent) for part in result)
        ):
            # A list of rows, empty or not, has nowhere to say it: its tool promises rows, and a
            # text part among them would make the whole answer fail. The next answer will say it.
            return result
        notices = dict(untold)
        untold.clear()
        if client.get("name") != CLAUDE_CODE:
            # Connect refreshes Claude Code's entry only. Another client started the same way,
            # like the Claude desktop app, would hear it every session and can't act on it.
            notices.pop("moah_connection", None)
        if (restart := watch.notice(session)) is not None:
            notices = {"moah_updated": restart, **notices}
        if not notices:
            return result
        if isinstance(result, str):
            return "\n\n".join([*notices.values(), result])
        if isinstance(result, dict):
            return {**notices, **result}
        return [*(TextContent(type="text", text=text) for text in notices.values()), *result]

    def pick(session: Session, project: str | None, cwd: str | None = None, *, write: bool = False):
        try:
            found, how = resolve_project(session, project, cwd, default_project)
        except ProjectChoiceError:
            # A server shared by several folders (a desktop app) runs in none of them: the
            # project this session's brief matched is the one the agent is working in, so a
            # call that names neither a project nor a folder goes there, as the brief says.
            remembered = briefed.get("project")
            if (project or "").strip() or cwd is not None or remembered is None:
                raise
            found, how = resolve_project(session, remembered, None)[0], "this session's brief"
        if write and found.status == "archived":
            raise ValueError(f"{found.name} is archived. Ask a person to restore it first.")
        return found, how

    def file_on_shelf(
        session: Session,
        project_id: str,
        memory_id: str,
        text: str,
        shelf: str | None,
        kind: str = "memory",
    ) -> dict:
        """Put a new record on the shelf named, or, when it is on none yet (a tag with a shelf's
        name counts), on the shelf its words, its project's other records and the records it is
        linked to support best. Call it after the record's links are written."""
        service = ShelfService(session)
        node = f"{kind}:{memory_id}"
        if shelf is not None:
            try:
                return {
                    "shelf": service.path(service.place(project_id, shelf, [node], actor=agent))
                }
            except HTTPException:
                return {"shelf_not_found": shelf}
        own = service.memberships(project_id)
        _, shared = service.shared(project_id)
        if any(Node(kind, memory_id) in nodes for nodes in [*own.values(), *shared.values()]):
            return {}
        record = Node(kind, memory_id)
        near = {
            other
            for edge, other, _ in service.graph.neighbours(project_id, record)
            if edge.status in TRAVERSABLE_STATUSES and other != record
        }
        best = service.suggest(project_id, text, near)
        if best is None:
            return {}
        service.place(project_id, best.id, [node], actor=agent)
        return {
            "shelf": ("shared: " if best.scope == "global" else "") + best.path,
            "filed": "automatically; if it belongs elsewhere, move it with brain_update_shelf",
        }

    def session_task(session: Session, project_id: str) -> str | None:
        task = working.current(session, project_id)
        return task.human_id if task else None

    def in_brief(session: Session, project_id: str) -> bool:
        """Whether this session's brief showed the project's rules and unfinished task. Every
        brief shows the Global rules."""
        if project_id == GLOBAL_PROJECT_ID:
            return True
        if "project" not in briefed:
            try:  # the start-up hook's brief: the folder this server was started in
                found, _ = resolve_project(session, None, None, default_project)
            except ProjectChoiceError:
                return False
            return found.id == project_id
        return briefed["project"] == project_id

    kit = ToolKit(
        tool=tool,
        pick=pick,
        agent=agent,
        actor=actor,
        working=working,
        packs=packs,
        briefed=briefed,
        session_task=session_task,
        in_brief=in_brief,
        file_on_shelf=file_on_shelf,
        session_factory=session_factory,
    )
    register_all(kit)

    compact_tools(server)
    return server


if __name__ == "__main__":  # `python -m app.mcp.server`, as source installs were connected
    raise SystemExit(main())

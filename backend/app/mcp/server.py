"""The Project Moah MCP server (stdio). One small tool set for retrieving and recording work.

Rules this adapter keeps:
- Agents never silently change locked memory or complete tasks. Those become proposals.
- Every write is attributed to the agent named in the server's settings.
- A project is chosen explicitly, or from the working directory only when unambiguous.
- Errors say what to do next; no stack traces reach the agent.
"""

from __future__ import annotations

import base64
import traceback
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ImageContent, TextContent, ToolAnnotations
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import UnboundExecutionError
from sqlalchemy.orm import Session, sessionmaker
from starlette.exceptions import HTTPException

from app.core import error_log
from app.mcp.cli import main, with_update_check  # noqa: F401 - old entry point
from app.mcp.linking import SessionPacks, SessionTask, link_written, sort_named
from app.mcp.projects import ProjectChoiceError, resolve_project
from app.models.checkpoint import ActivityEvent
from app.models.graph import OPERATIONS
from app.models.memory import Memory
from app.models.project import GLOBAL_PROJECT_ID, Project
from app.models.task import Task
from app.schemas.checkpoint import CheckpointCreate
from app.schemas.graph import ShelfUpdate
from app.schemas.memory import HUMAN, MemoryCreate, MemorySupersede, MemoryUpdate
from app.schemas.proposal import ProposalCreate
from app.schemas.review import AskPerson, ReviewSubmit
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.activity import acting_as
from app.services.agent_prompts import second_opinion
from app.services.agent_sessions import SessionTracker
from app.services.agent_sync import sync_quietly
from app.services.brief import build_brief, checkpoint_task, headline_tasks
from app.services.builds import UpdateWatch
from app.services.checkpoints import CheckpointService
from app.services.context import ContextService
from app.services.discovery import DiscoveryService, discover_checkpoint_quietly
from app.services.files import FileService
from app.services.graph import TRAVERSABLE_STATUSES, GraphService, Node
from app.services.images import ImageService
from app.services.memory import MemoryService
from app.services.projects import ProjectService
from app.services.proposals import ProposalService, actor_for
from app.services.retrieval import RetrievalService
from app.services.review_waits import waits_on_person
from app.services.reviews import (
    ANSWERED_IN_CHAT,
    CLOSED,
    STARTED_TAG,
    ReviewService,
    Screenshot,
)
from app.services.search import SearchService
from app.services.settings import get_agent_settings
from app.services.shelves import ShelfService
from app.services.tasks import TaskService
from app.services.update_check import install_steps, take_daily_check

# In the system prompt of every session, next to the brief, so it says only what a client
# without the start-up hook needs to get the brief. The brief itself says when to fetch more.
INSTRUCTIONS = """\
Project Moah is the person's shared memory for Claude Code and Codex: rules, decisions, tasks
and checkpoints for every project. At the start of a session, call brain_brief with your working
folder as cwd, unless its brief is already in your context, and follow it. Their earlier answers
are here, so check Moah (brain_context_pack or brain_search) before you ask them anything.
Writing records and checkpoints is part of the work and needs no permission. Global rules,
global decisions and locked records go to the person as proposals (brain_create_proposal). Each
request, however small, is a task of its own (brain_create_task unless an open one covers it):
hand it over with brain_submit_review when done, and ask with brain_ask_person when you stop for
an answer."""

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
)


ANY_WORD_NOTE = "any word: no record has every word of the query, so these share some of them"
# A plain question matches many records on one word each: the best few are enough.
ANY_WORD_LIMIT = 5
DUPLICATE_SHARED = 2  # meaningful title words a possible duplicate must share
DUPLICATE_HINT = (
    "If one of these already says it, use brain_update_memory or brain_supersede_memory "
    "instead of keeping two records."
)

# A task Moah starts for work an agent did without one, once that work waits for the person.
STARTED_BY_MOAH = (
    "Started by Project Moah: an agent worked without a task and stopped to wait for you. "
    "Rename it, merge it into the task it belongs to, or archive it if it was nothing."
)
TASK_TITLE_LIMIT = 200
# Said when an agent waits on a task the person already closed (ReviewService.follow_up).
FOLLOW_UP_NOTE = (
    "{closed} is already closed, so this waits in {task}, the follow-up Moah keeps for it. Go "
    "on in {task}; this session's next notes land there."
)

# Finished work always reaches the person: a task moved to review without the agent's report
# gets one Moah drafts from its checkpoints, and the agent is asked for a better one. (Refusing
# the move kept finished work out of Review, since agents seldom write the report.)
REVIEW_DRAFTED = (
    "{task} waits in the person's Review screen with a report Moah drafted from your "
    'checkpoints. Write a better one now with brain_submit_review(task="{task}", summary, done, '
    "not_done, how_to_check, screenshots): it replaces the draft. Writing it needs no "
    "permission. Finished several tasks? Submit one review for each."
)


ASK_HINT = (
    "Not asked yet: if you need the person's answer to go on, now call "
    'brain_ask_person(task="{task}", question, options). The question waits in Project Moah\'s '
    "Review screen until they answer; a chat reply may never reach them."
)
TEXT_ATTACHMENT_LIMIT = 4000
ARCHIVE_LIMIT = 200  # tasks one brain_archive_tasks call may change
# Where a restored task goes, by the column it was archived from. Review and Blocked wait on
# a report or a question that archiving settled, so those come back as To do.
RESTORE_TO = {"completed": "completed", "backlog": "backlog"}


def status_before_archive(session: Session, task_id: str) -> str:
    """The column a task goes back to when restored from the archive."""
    event = session.scalar(
        select(ActivityEvent)
        .where(ActivityEvent.task_id == task_id, ActivityEvent.event_type == "TASK_ARCHIVED")
        .order_by(ActivityEvent.timestamp.desc())
        .limit(1)
    )
    previous = (event.metadata_json or {}).get("previous_status") if event else None
    return RESTORE_TO.get(previous or "", "todo")


def review_drop_folder(session: Session) -> Path | None:
    """Where agents save screenshots when this server runs in the Flatpak sandbox, which can
    read only its own data folder. None outside the sandbox: any path works there."""
    if not Path("/.flatpak-info").exists():
        return None
    try:
        database = session.get_bind().url.database
    except UnboundExecutionError:  # a server built only to count its tools has no database
        return None
    if not database:
        return None
    return Path(database).resolve().parent / "review-files"


def review_drop_folder_for(session_factory: sessionmaker[Session]) -> Path | None:
    with session_factory() as session:
        return review_drop_folder(session)


def read_screenshots(
    paths: list[str], captions: list[str] | None, drop: Path | None
) -> list[Screenshot]:
    """The screenshot files an agent named, read from disk. Relative paths start at the folder
    this server runs in, which is the agent's working folder."""
    from app.models.review import MAX_REVIEW_FILE_BYTES

    hint = (
        f" This Project Moah runs in a Flatpak sandbox and reads screenshots only from {drop}:"
        " save or copy them there and pass those paths."
        if drop is not None
        else ""
    )
    shots = []
    for index, raw in enumerate(paths):
        path = Path(raw.strip()).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        try:
            if not path.is_file():
                raise ValueError(f"No screenshot file at {raw}.{hint}")
            if path.stat().st_size > MAX_REVIEW_FILE_BYTES:
                raise ValueError(f"{raw} is over 5 MB: save a smaller PNG or a JPEG.")
            data = path.read_bytes()
        except OSError:
            raise ValueError(f"Project Moah can't read {raw}.{hint}") from None
        caption = captions[index] if captions and index < len(captions) else None
        shots.append(Screenshot(data=data, filename=path.name, caption=caption))
    return shots


def clear_dropped(paths: list[str], drop: Path | None) -> None:
    """Screenshots saved in the drop folder are in the database now: remove the copies."""
    if drop is None:
        return
    for raw in paths:
        path = Path(raw.strip()).expanduser()
        try:
            if path.resolve().parent == drop.resolve():
                path.unlink(missing_ok=True)
        except OSError:
            pass


def review_for_agent(session: Session, task_id: str) -> dict:
    """The latest review round of a task, as an agent needs it: the person's verdict, comment
    and attachments (text files inline, pictures through brain_view_images)."""
    reviews = ReviewService(session)
    latest = reviews.latest(task_id)
    if latest is None:
        return {}
    question = latest.kind == "question"
    state = {
        "pending": f"waiting for the person's {'answer' if question else 'review'}",
        "accepted": "accepted by the person",
        "rejected": "sent back by the person: fix what the comment asks, then submit again",
        "answered": "answered by the person: go on with the task using their answer",
    }[latest.status]
    if latest.moved_to == ANSWERED_IN_CHAT:
        state = "answered by the person in the chat: go on with the task using their answer"
    elif latest.moved_to and not latest.comment:
        state = f"{state.split(':')[0]} by moving the task to {latest.moved_to} on the board"
    review: dict[str, Any] = {
        "round": latest.round,
        "status": state,
        "submitted_by": latest.agent,
        "question" if question else "summary": latest.summary,
    }
    if question and latest.options:
        review["options"] = list(latest.options)
    if latest.status != "pending":
        review["comment"] = latest.comment or ""
        files = reviews.feedback_files(latest.id)
        if files:
            review["attachments"] = []
            for row in files:
                entry: dict[str, Any] = {"id": row.id, "filename": row.filename}
                if row.media_type == "text/plain":
                    text = row.data.decode("utf-8", errors="replace")
                    if len(text) > TEXT_ATTACHMENT_LIMIT:
                        text = text[:TEXT_ATTACHMENT_LIMIT] + "\n[cut]"
                    entry["text"] = text
                else:
                    entry["view"] = f'brain_view_images(record="{row.id}")'
                review["attachments"].append(entry)
    return {"review": review}


GLOBAL_PERSON_TYPES = ("rule", "decision")
GLOBAL_RULE_MESSAGE = (
    "Global rules and decisions are the person's to set. Suggest it with "
    'brain_create_proposal(proposal_type="{kind}", project="global").'
)


TASK_DUPLICATE_HINT = (
    "If one of these is the same work, use it (brain_update_task) instead of keeping two tasks."
)
DONE_TASK_STATUSES = ("completed", "archived")


def possible_duplicate_tasks(session: Session, project_id: str, task_id: str, title: str) -> dict:
    """Up to three unfinished tasks whose titles share at least two meaningful words with
    ``title`` (its only one, for a one-word title): every request gets a task now, so the same
    request asked twice must not quietly become two. Empty when none match."""
    from app.services.context import match_keys

    def words(text: str) -> set[str]:
        return {k for k in match_keys(text) if len(k) > 2}

    own = words(title)
    if not own:
        return {}
    try:
        hits = SearchService(session).search(
            title, project_id=project_id, entity_types=["task"], any_word=True, limit=20
        )
    except Exception:  # noqa: BLE001 - the task is saved; a hint must never fail the write
        session.rollback()
        return {}
    same = [
        {"id": h["human_id"], "title": h["title"], "status": h["status"]}
        for h in hits["items"]
        if h["entity_id"] != task_id
        and h["status"] not in DONE_TASK_STATUSES
        and len(own & words(h["title"])) >= min(DUPLICATE_SHARED, len(own))
    ][:3]
    return {"possible_duplicates": same, "duplicates_hint": TASK_DUPLICATE_HINT} if same else {}


def refuse_global_rule(project: Project, memory: Memory) -> None:
    """Agents may not change a global rule or decision directly; it must be proposed."""
    if project.kind == "global" and memory.type in GLOBAL_PERSON_TYPES:
        raise ValueError(GLOBAL_RULE_MESSAGE.format(kind="update_memory"))


def possible_duplicates(
    session: Session, project_id: str, memory_id: str, memory_type: str, title: str
) -> dict:
    """Up to three active records of the same type whose titles share at least two meaningful
    words with ``title`` (its only one, for a one-word title), so an agent recording an answer
    can see whether Moah already said it. Words in a record's content do not count: a shared
    word there says little about the same thing being said twice. Empty when none match."""
    from app.services.context import match_keys

    def words(text: str) -> set[str]:
        return {k for k in match_keys(text) if len(k) > 2}  # "no", "up": no topic of their own

    own = words(title)
    if not own:
        return {}
    try:
        hits = SearchService(session).search(
            title,
            project_id=project_id,
            entity_types=["memory"],
            memory_types=[memory_type],
            for_agent=True,
            any_word=True,
            limit=20,
        )
    except Exception:  # noqa: BLE001 - the record is saved; a hint must never fail the write
        session.rollback()
        return {}
    same = [
        {"id": h["human_id"], "title": h["title"]}
        for h in hits["items"]
        if h["entity_id"] != memory_id
        and len(own & words(h["title"])) >= min(DUPLICATE_SHARED, len(own))
    ][:3]
    return {"possible_duplicates": same, "duplicates_hint": DUPLICATE_HINT} if same else {}


NEAR_MISS = "all words but one"


def near_misses(
    search: SearchService, query: str, found: list[dict], options: dict[str, Any], room: int
) -> list[dict]:
    """Records with every meaningful word of the query but one, best first, that ``found``
    does not hold yet. Only for three words or more: of two, one word is too loose a match."""
    from app.services.search import STOPWORDS, TERM_PATTERN

    terms = list(
        dict.fromkeys(t for t in TERM_PATTERN.findall(query) if t.casefold() not in STOPWORDS)
    )
    if len(terms) < 3 or room <= 0:
        return []
    seen = {(h["entity_type"], h["entity_id"]) for h in found}
    extra: list[dict] = []
    for index in range(len(terms)):
        rest = " ".join(terms[:index] + terms[index + 1 :])
        for hit in search.search(rest, **{**options, "limit": room})["items"]:
            key = (hit["entity_type"], hit["entity_id"])
            if key not in seen:
                seen.add(key)
                extra.append(hit)
    extra.sort(key=lambda h: -h["score"])
    return extra[:room]


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
        except ProjectChoiceError:  # no project for the folder: adopt by time alone
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

    @tool(READ)
    def brain_brief(
        session: Session,
        cwd: str | None = None,
        project: str | None = None,
        update_steps: bool = False,
    ) -> str:
        """Start here, once per session. Returns the person's global rules, the project's rules,
        the unfinished task with what is already decided for it, the latest checkpoint, and how
        to keep Project Moah current. Pass your working folder as cwd. Works outside any project
        too: then only global rules apply. update_steps=true returns only the steps to install a
        Project Moah update on this system, once the person said yes to one."""
        if update_steps:
            return install_steps()  # mid-session: the session and its packs stay as they are
        working.clear()  # a new session starts with no task of its own
        packs.clear()  # and has been sent nothing yet
        sync_quietly(session)  # a folder first seen in this session gets its project now
        try:
            found, _ = pick(session, project, cwd)
            note = hint = None
        except ProjectChoiceError as error:
            found, note, hint = None, str(error), error.hint
        briefed["project"] = found.id if found is not None and found.kind != "global" else None
        return with_update_check(session, build_brief(session, found, note, hint))

    @tool(READ)
    def brain_second_opinion(
        session: Session,
        question: str,
        task: str | None = None,
        project: str | None = None,
        cwd: str | None = None,
    ) -> dict:
        """Use ONLY when the person explicitly asks in this session for a second opinion from the
        other agent (Claude asks Codex; Codex asks Claude). Returns a read-only command to run in
        your terminal, with the question, the task and project context, and how to present and
        save both views. Refused when the person has switched second opinions off."""
        found, _ = pick(session, project, cwd)
        return second_opinion(
            session, get_agent_settings(session), found, agent, question, task, cwd
        )

    @tool(READ)
    def brain_list_projects(session: Session) -> list[dict]:
        """List Project Moah projects, so you can choose one explicitly. Rules and memory for every
        project live in the Global scope: pass project="global"."""
        return [
            {
                "id": p.id,
                "name": p.name,
                "slug": p.slug,
                "status": p.status,
                "repository": p.root_path,
            }
            for p in ProjectService(session).list()
        ]

    @tool(READ)
    def brain_project_state(
        session: Session, project: str | None = None, cwd: str | None = None
    ) -> dict:
        """Identify the project and summarize where work stands: focus task, counts, latest checkpoint,
        pending reviews, and Git status. Pass project, or cwd to match a repository folder."""
        found, how = pick(session, project, cwd)
        tasks = TaskService(session)
        overview = tasks.overviews([found.id])[0]
        latest = CheckpointService(session).list(found.id, limit=1)
        git = FileService(session).git.status(found)
        pending = ProposalService(session).pending_count(found.id)
        return {
            "project": {
                "id": found.id,
                "name": found.name,
                "slug": found.slug,
                "status": found.status,
                "repository": found.root_path,
                "found_by": how,
            },
            "current_focus": overview.focus_task.model_dump(mode="json")
            if overview.focus_task
            else None,
            "milestone": overview.active_milestone.model_dump(mode="json")
            if overview.active_milestone
            else None,
            "task_counts": overview.task_counts,
            "latest_checkpoint": (
                {
                    "id": latest[0].id,
                    "title": latest[0].title,
                    "next_steps": latest[0].next_steps,
                    "remaining_work": latest[0].remaining_work,
                    "task": latest[0].task.human_id if latest[0].task else None,
                }
                if latest
                else None
            ),
            "pending_proposals": pending,
            "session_task": session_task(session, found.id),
            "git": {
                "state": git.state,
                "branch": git.branch,
                "clean": git.clean,
                "changed_files": git.changed_total,
            },
        }

    @tool(READ)
    def brain_context_pack(
        session: Session,
        task: str | None = None,
        project: str | None = None,
        detail: str = "balanced",
        budget: int | None = None,
        query: str | None = None,
        include: list[str] | None = None,
        operation: str | None = None,
        explain: bool = False,
        global_rules: bool = False,
        full: bool = False,
    ) -> str:
        """A compact, ranked context pack: the task with its decisions, rules, warnings, bugs,
        files and latest checkpoint. Call it when you continue unfinished work, start or switch
        a task, a request names an ID, you need history or traps, before an unfamiliar area,
        when debugging, and before asking the person a question (query = the question). Skip
        it only for small edits or when a pack from this session already covers the work.
        task is an ID such as CAMP-037; without it, the pack keeps to this session's task, or
        picks the task the work is about, and says which. detail is minimal, balanced or
        detailed. explain=true says why each record came.
        Rules your brief gave are left out; pass global_rules=true if you never got the brief.
        The pack's task becomes this session's task. A repeat sends only what is new; full=true
        sends everything again."""
        found, _ = pick(session, project)
        if operation is not None and operation not in OPERATIONS:
            raise ValueError(f"operation must be one of: {', '.join(OPERATIONS)}")
        sent = packs.get(session, found.id)
        if full:
            sent.resend()  # send everything; later repeats count from this pack
        own = working.current(session, found.id)
        pack = ContextService(session).build(
            found.id,
            task=task,
            query=query,
            detail=detail,  # type: ignore[arg-type]
            budget=budget,
            include=include,
            operation=operation,
            record_for=agent,
            global_rules=global_rules,
            sent=sent,
            for_agent=not explain,
            session_task=own.id if own is not None else None,
            # The brief left out of the pack must be one this session got.
            in_brief=not global_rules and in_brief(session, found.id),
        )
        before = own.human_id if own is not None else None
        if pack.task and (pack.task_source != "focus" or not query):
            # The work this pack is for: the task asked for, the session's own, or (with no
            # session task yet) the one the request names or plainly matches. A pack for a
            # search alone only borrows the focus task.
            working.set(found.id, TaskService(session).get(found.id, pack.task).id)
        current = session_task(session, found.id)
        if pack.repeat_of is not None and not pack.retrieval_id:
            # Nothing new: a line, not a pack. The agent already has the rest; the tool's
            # description says how to get it all again (full=true).
            text = pack.text
            if current != before:
                text += f"\nThis session's task is {current}: what you write now is linked to it."
            if check := take_daily_check(session):
                text += "\n\n" + check
            return text
        # The footer keeps to what the agent acts on. Sizes, the kind of work and what was left
        # out are for explain=true.
        footer = list(pack.warnings)
        if explain:
            notes = [f"~{pack.estimated_tokens} tokens", f"operation {pack.operation}"]
            if pack.omitted:
                notes.append(
                    "left out: " + ", ".join(f"{n} {why}" for why, n in pack.omitted.items())
                )
            footer.insert(0, "; ".join(notes) + ".")
        if current and (current != before or pack.repeat_of is None):
            footer.append(f"This session's task is {current}: what you write now is linked to it.")
        if pack.retrieval_id:
            footer.append(
                "When done: brain_create_checkpoint naming the records that helped (counts as"
                " feedback), or brain_retrieval_feedback("
                f'retrieval="R-{pack.retrieval_id[:8]}", useful=[...], not_useful=[...]).'
            )
        if check := take_daily_check(session):
            # The day's check had not been given yet: this session started without a brief.
            footer.append("\n" + check)
        text = pack.text
        if explain:
            why = [
                f"- {i.title[:70]}"
                + (f" ({round(i.confidence * 100)}%)" if i.confidence else "")
                + f": {i.reason}"
                for i in pack.items
                if i.kind.startswith(("memory", "file"))
            ]
            near = [
                f"- {x.title[:70]}"
                + (f" ({round(x.confidence * 100)}%)" if x.confidence else "")
                + f": {x.reason}"
                for x in pack.excluded
            ]
            text += "\n\nWHY THESE\n" + ("\n".join(why) or "- nothing beyond the task")
            if near:
                text += "\n\nCAME CLOSE, LEFT OUT\n" + "\n".join(near)
        return text + ("\n\n---\n" + "\n".join(footer) if footer else "")

    @tool(WRITE)
    def brain_retrieval_feedback(
        session: Session,
        retrieval: str,
        useful: list[str] | None = None,
        not_useful: list[str] | None = None,
        project: str | None = None,
    ) -> dict:
        """Say which records of a context pack helped (useful) and which were noise
        (not_useful), by ID (DEC-003, file:src/a.gd). retrieval is the R-... id at the end of
        the pack. A checkpoint naming the records that helped already counts them; each verdict
        counts once. Links that brought useful records grow stronger for this kind of work,
        links that brought noise weaker. A useful record the pack missed gets linked to the
        task."""
        if not useful and not not_useful:
            raise ValueError("Name at least one record in useful or not_useful.")
        found, _ = pick(session, project, write=True)
        return RetrievalService(session).feedback(
            found.id,
            retrieval,
            useful=useful or [],
            not_useful=not_useful or [],
            actor=agent,
            session_refs=packs.get(session, found.id).retrievals,
        )

    @tool(READ)
    def brain_link_review(session: Session, project: str | None = None) -> dict:
        """What the Link System is unsure about: candidate links it inferred but nobody has
        confirmed, and orphan memory with no links or shelf. Confirm a candidate by asserting it
        with brain_link; reject it with brain_link(remove=true). Also the graph's health and
        shelves the brain suggests growing or merging; those are for the person to accept in
        the app."""
        from app.services.health import HealthService

        found, _ = pick(session, project)
        service = DiscoveryService(session)
        health = HealthService(session)
        stats = health.project(found.id)
        return {
            "health": {k: v for k, v in stats.items() if k not in ("density", "clusters")},
            "shelf_suggestions": [s["message"] for s in health.suggestions(found.id)],
            "candidates": [
                {
                    "link": f"{c['source'].label} {c['relationship']} {c['target'].label}",
                    "titles": f"{c['source'].title} / {c['target'].title}",
                    "confidence": c["confidence"],
                    "why": c["why"],
                }
                for c in service.candidates(found.id, limit=30)
            ],
            "orphans": [
                f"{o['id']} ({o['type']}): {o['title']}"
                for o in service.orphans(found.id, limit=30)
            ],
        }

    @tool(READ)
    def brain_get_task(session: Session, task: str, project: str | None = None) -> dict:
        """Full detail for one task: description, acceptance criteria, relationships, and milestone."""
        found, _ = pick(session, project)
        detail = TaskService(session).detail(found.id, task)
        return {**detail.model_dump(mode="json"), **review_for_agent(session, detail.id)}

    @tool(READ)
    def brain_view_images(session: Session, record: str, project: str | None = None) -> list:
        """See the images a person attached to a task or memory record (PROJ-6, DEC-3, or one
        image's id). Records that have images list them under images; this returns the pictures
        themselves, so look at them before working from the record. For a task sent back from
        review, it also shows the pictures the person attached to their comment."""
        found, _ = pick(session, project)
        reviews = ReviewService(session)
        attached = reviews.find_file(record.strip())
        if attached is not None and attached.project_id in (found.id, GLOBAL_PROJECT_ID):
            if attached.media_type == "text/plain":
                return [TextContent(type="text", text=attached.data.decode("utf-8", "replace"))]
            return [
                TextContent(type="text", text=f"{attached.filename} ({attached.media_type})"),
                ImageContent(
                    type="image",
                    data=base64.b64encode(attached.data).decode(),
                    mime_type=attached.media_type,
                ),
            ]
        service = ImageService(session)
        try:
            one = service.get(found.id, record.strip())
            kind, owner_id = ("task", one.task_id) if one.task_id else ("memory", one.memory_id)
        except HTTPException:
            one = None
            node = GraphService(session).resolve(found.id, record, allow_global=True)
            if node.kind not in ("task", "memory"):
                raise ValueError("Only tasks and memory records have images.") from None
            kind, owner_id = node.kind, node.id
        row = session.get(Task if kind == "task" else Memory, owner_id)
        if kind == "memory" and row.ai_visibility == "hidden":
            raise ValueError(f"{row.human_id} is hidden from agents.")
        images = (
            [one]
            if one
            else [
                service.get(row.project_id, ref.id)
                for ref in service.for_records(kind, [owner_id])[owner_id]
            ]
        )
        if one is None and kind == "task":
            latest = reviews.latest(owner_id)
            if latest is not None and latest.status == "rejected":
                images += [
                    f for f in reviews.feedback_files(latest.id) if f.media_type != "text/plain"
                ]
        if not images:
            return [TextContent(type="text", text=f"{row.human_id} has no images.")]
        blocks: list = []
        for index, image in enumerate(images, 1):
            size = f", {image.width}x{image.height}" if image.width else ""
            blocks.append(
                TextContent(
                    type="text",
                    text=f"{row.human_id} image {index} of {len(images)}: {image.filename}"
                    f" ({image.media_type}{size}, id {image.id})",
                )
            )
            blocks.append(
                ImageContent(
                    type="image",
                    data=base64.b64encode(image.data).decode(),
                    mime_type=image.media_type,
                )
            )
        return blocks

    @tool(READ)
    def brain_list_tasks(
        session: Session,
        project: str | None = None,
        status: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """List tasks compactly. status can be backlog, todo, in_progress, blocked, review, completed."""
        found, _ = pick(session, project)
        rows = TaskService(session).list(found.id, statuses=status)[: max(1, min(limit, 200))]
        return [
            {
                "id": t.human_id,
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "criteria": f"{t.criteria_completed}/{t.criteria_total}",
                "focus": t.is_focus,
                "waiting_on_dependency": t.is_blocked_by_open_dependency,
            }
            for t in rows
        ]

    @tool(READ)
    def brain_search(
        session: Session,
        query: str,
        project: str | None = None,
        scope: str = "project",
        types: list[str] | None = None,
        limit: int = 10,
    ) -> dict:
        """Search tasks, memory, checkpoints and files. A plain question works: when no record has
        every word, records with any of them are returned, best first. scope is 'project'
        (default) or 'all'; results from all projects are for reading only and must not be
        treated as this project's truth."""
        search = SearchService(session)
        options: dict[str, Any] = {
            "entity_types": types,
            "for_agent": True,
            "limit": max(1, min(limit, 50)),
        }
        if scope == "project":
            options["project_id"] = pick(session, project)[0].id
        elif scope != "all":
            raise ValueError("scope must be 'project' or 'all'")
        result = search.search(query, **options)
        loose = False
        if not result["total"]:
            # Agents type questions, not keywords: "which day does the week start" has no
            # record with every word, but "Weeks start on Monday" shares some of them. Checking
            # before asking the person must stay cheaper than a pack: the best few only.
            options["limit"] = min(options["limit"], ANY_WORD_LIMIT)
            result = search.search(query, any_word=True, **options)
            loose = bool(result["total"])
        # In one project the project's name says nothing; loose matches skip status too.
        keys = ["entity_type", "human_id", "title", "snippet"]
        keys += [] if loose else ["status"]
        keys += ["project_name"] if scope == "all" else []
        rows = [{k: h[k] for k in keys} for h in result["items"]]
        total = result["total"]
        if not loose and 0 < total < ANY_WORD_LIMIT:
            # One weak record with every word (a checkpoint quoting the query) must not hide
            # the decision that has all but one of them: "offline gold cap" finds "Offline gold
            # started" and "Offline gains: at most 8 hours" ("offline", "gold" in its text).
            extra = near_misses(search, query, result["items"], options, ANY_WORD_LIMIT - total)
            rows += [
                {**{k: h[k] for k in keys if k != "status"}, "match": NEAR_MISS} for h in extra
            ]
            total += len(extra)
        return {
            **({"matched": ANY_WORD_NOTE} if loose else {}),
            "total": total,
            "results": rows,
        }

    @tool(READ)
    def brain_get_related(session: Session, task: str, project: str | None = None) -> dict:
        """Everything linked to a task: related tasks, memory, files, checkpoints, and commits."""
        found, _ = pick(session, project)
        detail = TaskService(session).detail(found.id, task)
        files = FileService(session)
        memory = MemoryService(session).list(found.id, task=detail.id)
        return {
            "task": detail.human_id,
            "relationships": [
                {
                    "type": r.type,
                    "task": r.task.human_id,
                    "title": r.task.title,
                    "status": r.task.status,
                }
                for r in detail.relationships
            ],
            "memory": [
                {
                    "id": m.human_id,
                    "type": m.type,
                    "title": m.title,
                    "locked": m.is_locked,
                    "visibility": m.ai_visibility,
                }
                for m in memory
            ],
            "files": [
                {"path": f.path, "purpose": f.purpose, "why": why}
                for f, why in files.files_for_task(found.id, detail.id)
            ],
            "checkpoints": [
                {"id": c.id, "title": c.title, "summary": c.summary}
                for c in CheckpointService(session).list(found.id, task=detail.id, limit=5)
            ],
            "commits": [
                {"sha": c.short_sha, "subject": c.subject}
                for c in files.commits(found.id, task=detail.id).commits
            ],
        }

    @tool(READ)
    def brain_changed_files(session: Session, project: str | None = None) -> dict:
        """Files changed in the working tree right now, with any notes Project Moah holds about them."""
        found, _ = pick(session, project)
        files = FileService(session)
        git = files.git.status(found)
        notes = {f.path: f for f in files.list(found.id)}
        return {
            "git_state": git.state,
            "message": git.message if git.state != "ok" else None,
            "branch": git.branch,
            "total_changed": git.changed_total,
            "changed": [
                {
                    "path": c.path,
                    "status": c.status,
                    "purpose": notes[c.path].purpose if c.path in notes else None,
                    "tasks": [t.human_id for t in notes[c.path].tasks] if c.path in notes else [],
                }
                for c in git.changed
            ],
        }

    @tool(WRITE)
    def brain_create_task(
        session: Session,
        title: str,
        project: str | None = None,
        description: str | None = None,
        prefix: str | None = None,
        priority: str = "normal",
        status: str = "todo",
        next_action: str | None = None,
        acceptance_criteria: list[str] | None = None,
        tags: list[str] | None = None,
        milestone: str | None = None,
        links: list[str] | None = None,
    ) -> dict:
        """Create a task. It starts as todo or backlog; people decide when work is complete.
        links adds typed links, each written "relationship target" ("caused_by BUG-002"). A task
        created while this session works on another task is linked to that task."""
        found, _ = pick(session, project, write=True)
        if status not in ("backlog", "todo"):
            raise ValueError("New tasks can start as 'backlog' or 'todo'.")
        task = TaskService(session).create(
            found.id,
            TaskCreate(
                title=title,
                description=description,
                prefix=prefix,
                priority=priority,
                status=status,  # type: ignore[arg-type]
                next_action=next_action,
                acceptance_criteria=acceptance_criteria or [],
                tags=tags or [],
                milestone_id=milestone,
            ),
        )
        linked = link_written(
            session,
            found.id,
            f"task:{task.id}",
            actor=agent,
            links=links or [],
            session_task=working.current(session, found.id),
        )
        return {
            "created": task.human_id,
            "title": task.title,
            "status": task.status,
            **file_on_shelf(
                session, found.id, task.id, f"{title} {description or ''}", None, kind="task"
            ),
            **linked,
            **possible_duplicate_tasks(session, found.id, task.id, task.title),
        }

    @tool(WRITE)
    def brain_update_task(
        session: Session,
        task: str,
        project: str | None = None,
        next_action: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        reason: str = "",
        links: list[str] | None = None,
    ) -> dict:
        """Update a task's working fields. A finished task goes to the person's review: hand it
        over with brain_submit_review, which writes your report and moves it to review (status
        completed or review alone moves it there with a report Moah drafts from your
        checkpoints). Archiving becomes a proposal. Setting status in_progress makes it this
        session's task. links adds typed links, each written "relationship target"
        ("blocked_by PROJ-4")."""
        found, _ = pick(session, project, write=True)
        changes = {
            k: v
            for k, v in dict(
                next_action=next_action,
                status=status,
                priority=priority,
                description=description,
                tags=tags,
            ).items()
            if v is not None
        }
        if not changes and not links:
            raise ValueError("Give at least one field to change.")
        drafted = False
        if status in ("completed", "review"):
            # People decide when work is complete: a finished task waits in review.
            current = TaskService(session).get(found.id, task)
            if current.status in ("completed", "archived"):
                raise ValueError(
                    f"{current.human_id} is already {current.status}. Nothing changed."
                )
            drafted = ReviewService(session).submitted_review(current.id) is None
            changes["status"] = status = "review"
        if changes:  # links alone change no field: nothing to check
            TaskUpdate.model_validate(changes)
        proposals = ProposalService(session)
        if status == "archived":
            p = proposals.create(
                found.id,
                ProposalCreate(
                    proposal_type="update_task",
                    target=task,
                    payload=changes,
                    reason=reason or "Agent suggests archiving.",
                ),
                agent=agent,
            )
            return {
                "applied": False,
                "needs_review": True,
                "proposal": p.human_id,
                "message": "Archiving a task needs a person's review. A proposal was created.",
                **link_written(session, found.id, f"task:{task}", actor=agent, links=links or []),
            }
        tasks = TaskService(session)
        updated = (
            tasks.update(found.id, task, TaskUpdate.model_validate(changes))
            if changes
            else tasks.get(found.id, task)
        )
        if updated.status == "in_progress" and status == "in_progress":
            working.set(found.id, updated.id)
        result = {
            "applied": True,
            "task": updated.human_id,
            "status": updated.status,
            **link_written(session, found.id, f"task:{updated.id}", actor=agent, links=links or []),
        }
        if drafted:
            result["next"] = REVIEW_DRAFTED.format(task=updated.human_id)
        if status == "blocked" and ReviewService(session).asked_question(updated.id) is None:
            result["next"] = ASK_HINT.format(task=updated.human_id)
        return result

    @tool(WRITE)
    def brain_archive_tasks(
        session: Session,
        person_asked: str,
        tasks: list[str] | None = None,
        all_done: bool = False,
        restore: bool = False,
        project: str | None = None,
    ) -> dict:
        """Archive tasks, but ONLY when the person asked you to in this conversation: never on
        your own initiative, never to tidy up. Archived tasks leave the board and the brief but
        keep their history, and can be restored. person_asked: the person's own words asking
        for it, kept in each task's history. tasks: task IDs to archive. all_done: true
        archives every Done task of the project. restore: true takes the named tasks out of the
        archive instead (a Done task goes back to Done, any other to To do). Want to archive
        something the person did not ask for? Suggest it with brain_create_proposal."""
        asked = person_asked.strip()
        if len(asked) < 3:
            raise ValueError(
                "person_asked must quote the person's request. Archive only when they asked; "
                "otherwise suggest it with brain_create_proposal."
            )
        if restore and all_done:
            raise ValueError("Restore names its tasks: give tasks, not all_done.")
        if not tasks and not all_done:
            raise ValueError("Name the tasks, or set all_done to archive every Done task.")
        found, _ = pick(session, project, write=True)
        service = TaskService(session)
        refs = list(dict.fromkeys(tasks or []))
        if all_done:
            refs += [
                t.human_id
                for t in service.list(found.id, statuses=["completed"])
                if t.human_id not in refs
            ]
        if len(refs) > ARCHIVE_LIMIT:
            raise ValueError(f"At most {ARCHIVE_LIMIT} tasks at a time; got {len(refs)}.")
        note = {"asked_by_person": asked[:500], "by_agent_on_request": True}
        changed: list[dict] = []
        skipped: list[dict] = []
        for ref in refs:
            try:
                row = service.get(found.id, ref)
            except HTTPException:
                skipped.append({"task": ref, "why": "not found in this project"})
                continue
            if restore:
                if row.status != "archived":
                    skipped.append({"task": row.human_id, "why": f"not archived ({row.status})"})
                    continue
                back = status_before_archive(session, row.id)
                service.update(found.id, row.id, TaskUpdate(status=back), note)
                changed.append({"task": row.human_id, "title": row.title, "status": back})
            else:
                if row.status == "archived":
                    skipped.append({"task": row.human_id, "why": "already archived"})
                    continue
                was = row.status
                service.update(found.id, row.id, TaskUpdate(status="archived"), note)
                changed.append({"task": row.human_id, "title": row.title, "was": was})
        verb = "restored" if restore else "archived"
        result: dict = {verb: changed, "count": len(changed)}
        if skipped:
            result["skipped"] = skipped
        if not changed:
            result["message"] = f"Nothing {verb}."
        elif restore:
            result["message"] = "Tell the person which tasks are back on the board."
        else:
            result["message"] = (
                "Tell the person what you archived. They can restore a task from its details "
                "in Project Moah, or ask you: brain_archive_tasks(tasks=[...], restore=true, "
                'person_asked="...").'
            )
        return result

    @tool(WRITE)
    def brain_archive_memories(
        session: Session,
        person_asked: str,
        memories: list[str],
        restore: bool = False,
        project: str | None = None,
    ) -> dict:
        """Archive rules, decisions and other memory records, but ONLY when the person asked
        you to in this conversation: never on your own initiative, never to tidy up. Archived
        records leave the brief and context packs but keep their history, and can be restored.
        person_asked: the person's own words asking for it, kept in each record's history.
        memories: record IDs (RULE-015, DEC-004); project="global" for Global rules. restore:
        true brings archived records back. Locked records stay the person's: suggest those
        with brain_create_proposal, like anything the person did not ask for."""
        asked = person_asked.strip()
        if len(asked) < 3:
            raise ValueError(
                "person_asked must quote the person's request. Archive only when they asked; "
                "otherwise suggest it with brain_create_proposal."
            )
        refs = list(dict.fromkeys(memories))
        if not refs:
            raise ValueError("Name the records to archive.")
        if len(refs) > ARCHIVE_LIMIT:
            raise ValueError(f"At most {ARCHIVE_LIMIT} records at a time; got {len(refs)}.")
        found, _ = pick(session, project, write=True)
        service = MemoryService(session)
        note = {"asked_by_person": asked[:500], "by_agent_on_request": True}
        changed: list[dict] = []
        skipped: list[dict] = []
        for ref in refs:
            try:
                row = service.get(found.id, ref)
            except HTTPException:
                skipped.append({"memory": ref, "why": "not found in this project"})
                continue
            if row.is_locked:
                skipped.append(
                    {"memory": row.human_id, "why": "locked: only the person can change it"}
                )
                continue
            wanted = ("archived", "invalidated") if restore else ("active",)
            if row.status not in wanted:
                skipped.append({"memory": row.human_id, "why": f"it is {row.status}"})
                continue
            if restore:
                service.restore(found.id, row.id, actor=agent, note=note)
            else:
                service.archive(found.id, row.id, actor=agent, note=note)
            changed.append({"memory": row.human_id, "type": row.type, "title": row.title})
        verb = "restored" if restore else "archived"
        result: dict = {verb: changed, "count": len(changed)}
        if skipped:
            result["skipped"] = skipped
        result["message"] = (
            f"Nothing {verb}."
            if not changed
            else f"Tell the person what you {verb}."
            + (
                ""
                if restore
                else " They can restore a record from its details in Project Moah, or ask you "
                "(restore=true)."
            )
        )
        return result

    @tool(WRITE)
    def brain_ask_person(
        session: Session,
        task: str,
        question: str,
        context: str | None = None,
        options: list[str] | None = None,
        project: str | None = None,
    ) -> dict:
        """Ask the person something only they can answer when you cannot go on without it: a
        choice, a fact, an approval. Use it whenever you stop to ask, also when you ask in the
        chat: a chat question is easily lost, this one waits in Project Moah's Review screen
        until they answer. Check Moah first (brain_search): they may have answered before. The
        task moves to Blocked; the answer then shows in the brief and brain_get_task, and the
        task is in progress again. question: one or two plain sentences (several questions can
        go in one). context: optional Markdown on what you found and what each choice would
        mean. options: up to 6 short answers to pick from. Then stop; don't guess the answer."""
        found, _ = pick(session, project, write=True)
        payload = AskPerson(question=question, context=context, options=options or [])
        about = TaskService(session).get(found.id, task)
        closed = about.human_id if about.status in CLOSED else None
        review = ReviewService(session).ask(found.id, about.id, payload, agent)
        row = session.get(Task, review.task_id)
        working.set(found.id, row.id)
        result = {
            "asked": row.human_id,
            "status": row.status,
            "message": "It waits in the person's Review screen. Stop work on this task and tell "
            "them you asked; the brief shows their answer when it comes.",
        }
        if closed is not None and row.human_id != closed:
            result["task_started"] = FOLLOW_UP_NOTE.format(closed=closed, task=row.human_id)
        return result

    def brain_submit_review(
        session: Session,
        task: str,
        summary: str,
        done: list[str],
        not_done: list[str] | None = None,
        how_to_check: str | None = None,
        details: str | None = None,
        screenshots: list[str] | None = None,
        captions: list[str] | None = None,
        project: str | None = None,
    ) -> dict:
        """Hand a finished task to the person for review; it moves to status review and waits
        in Project Moah's Review screen until they accept it or send it back with comments.
        summary: two or three plain sentences on what changed for them. done: each thing
        finished, one short line each. not_done: what is left, skipped, failed or unverified
        (be honest; an empty list says everything was done). how_to_check: steps the person
        can follow to see it working. details: optional Markdown for anything else (tables,
        code, notes; "> [!WARNING]" makes a warning box). screenshots: image file paths (PNG,
        JPEG, WebP or GIF, up to 10, 5 MB each), with captions in the same order. Attach
        screenshots whenever the result is something the person can see (a screen, a page, a
        chart, a document, a game scene): take them with the tools you have, for example
        Playwright or a screenshot command. Submitting again replaces a review still waiting.
        After a send-back, brain_get_task shows the person's comment."""
        found, _ = pick(session, project, write=True)
        payload = ReviewSubmit(
            summary=summary,
            done=done,
            not_done=not_done or [],
            how_to_check=how_to_check,
            details=details,
        )
        drop = review_drop_folder(session)
        shots = read_screenshots(screenshots or [], captions, drop)
        review = ReviewService(session).submit(found.id, task, payload, agent, shots)
        clear_dropped(screenshots or [], drop)
        row = session.get(Task, review.task_id)
        working.set(found.id, row.id)
        result = {
            "submitted": row.human_id,
            "round": review.round,
            "status": row.status,
            "screenshots": len(shots),
            "message": "It waits in the person's Review screen. Don't keep working on it unless "
            "they send it back; the brief and brain_get_task then show their comment.",
        }
        if not shots:
            result["note"] = (
                "No screenshots attached. If the person can see the result, submit again with "
                "screenshots."
            )
        return result

    if (drop := review_drop_folder_for(session_factory)) is not None:
        brain_submit_review.__doc__ += (
            f" On this computer Project Moah runs in a sandbox: save screenshots in {drop}"
            " and pass those paths."
        )
    tool(WRITE)(brain_submit_review)

    @tool(WRITE)
    def brain_create_checkpoint(
        session: Session,
        title: str,
        summary: str = "",
        completed_work: str = "",
        remaining_work: str = "",
        problems: str = "",
        next_steps: str = "",
        task: str | None = None,
        project: str | None = None,
        git_commit: str | None = None,
        waiting_for_person: bool | None = None,
    ) -> dict:
        """Record where work stands so the next session can resume: after task work, before
        your final reply. task defaults to this session's task, else to the brief's unfinished
        task if the checkpoint names it or its records. Records it names (DEC-004, BUG-2, a file
        with notes) are linked to its task. Records your packs held that summary,
        completed_work or next_steps name count as useful feedback. waiting_for_person: true
        when you stop for the person's OK, pick or answer (a plan, a mockup, a commit): the
        title then waits in their Review screen as your question, and your next checkpoint
        settles it."""
        found, _ = pick(session, project, write=True)
        guessed = moved = None
        current = working.current(session, found.id) if task is None else None
        if task is None:
            # A note about another task belongs to it, not to the one the session last touched:
            # "IDLE-006 popup laid out" while the session's task is IDLE-005. Only when the
            # note's headline (its title, or the ref opening its summary) names exactly one
            # task, not as an aside ("unblocked by IDLE-005"), and not the session's own.
            named = headline_tasks(session, found, title, summary)
            if len(named) == 1 and (current is None or named[0].id != current.id):
                moved = named[0]
                task = moved.id
        if task is None and current is not None:
            task = current.id
        elif task is None:
            # Worked from the brief alone, with no pack: the brief's unfinished task, when the
            # checkpoint is about it, so the next brief does not show its old "Left to do".
            texts = [title, summary, completed_work, remaining_work, problems, next_steps]
            guessed = checkpoint_task(session, found, texts)
            task = guessed.id if guessed is not None else None
        waits = waits_on_person(title, waiting_for_person)
        started = followed = None
        if waits and task is not None:
            about = TaskService(session).get(found.id, task)
            if about.status in CLOSED:
                # The person already accepted (or archived) it: the wait goes to its follow-up.
                row, _ = ReviewService(session).follow_up(about, agent)
                followed, task = (about.human_id, row.human_id), row.id
        if waits and task is None and found.id != GLOBAL_PROJECT_ID:
            # Work that waits for the person needs a task to wait in Review with. The session
            # keeps it, so its later notes land on it too: one task per session, not per note.
            started = TaskService(session).create(
                found.id,
                TaskCreate(
                    title=" ".join(title.split())[:TASK_TITLE_LIMIT] or "Work waiting for you",
                    description=STARTED_BY_MOAH,
                    status="in_progress",
                    tags=[STARTED_TAG],
                ),
            )
            task = started.id
        cp = CheckpointService(session).create(
            found.id,
            CheckpointCreate(
                title=title,
                summary=summary,
                completed_work=completed_work,
                remaining_work=remaining_work,
                problems=problems,
                next_steps=next_steps,
                task_id=task,
                agent=agent,
                git_commit=git_commit,
            ),
            actor_type=actor,
            actor_name=agent,
        )
        if cp.task_id:
            working.set(found.id, cp.task_id)
        reviews, row = ReviewService(session), session.get(Task, cp.task_id) if cp.task_id else None
        waiting = reviews.wait_from_checkpoint(row, cp, agent) if waits and row else None
        if row is not None and not waits:
            reviews.moved_on(row)
        anchor = cp.task.human_id if cp.task else "this checkpoint"
        result = {
            "created": cp.id,
            "title": cp.title,
            "task": cp.task.human_id if cp.task else None,
            "links": [
                f"{anchor} references {label}"
                for label in discover_checkpoint_quietly(session, found.id, cp.id, agent)
            ],
        }
        if followed is not None:
            result["task_started"] = FOLLOW_UP_NOTE.format(closed=followed[0], task=followed[1])
        if started is not None:
            result["task_started"] = (
                f"No task was set, so Moah started {started.human_id} for this work. Pass "
                "task= next time if it belongs to another one."
            )
        if waiting is not None:
            result["review"] = (
                f"{cp.task.human_id} waits for the person in their Review screen. Stop and ask "
                "them; when you go on, your next checkpoint settles it."
            )
        if moved is not None:
            result["task_note"] = (
                f"Filed under {moved.human_id}, the task this checkpoint names"
                + (f", not this session's task {current.human_id}" if current else "")
                + f". {moved.human_id} is now this session's task; pass task= for another."
            )
        if guessed is not None:
            result["task_note"] = (
                f"{guessed.human_id} is the unfinished task in your brief and this checkpoint "
                "names it or its records. Pass task= for another."
            )
        # What the work used, in the agent's own words: records of this session's packs it
        # names as done or as the next step (not its problems) helped, unless it already said.
        helped = RetrievalService(session).feedback_from_checkpoint(
            found.id,
            packs.get(session, found.id).retrievals,
            [summary, completed_work, next_steps],
            actor=agent,
        )
        if helped:
            result["feedback"] = "; ".join(
                f"counted as feedback for {short}: {', '.join(ids)}" for short, ids in helped
            )
        return result

    @tool(WRITE)
    def brain_create_memory(
        session: Session,
        type: str,
        title: str,
        content: str = "",
        project: str | None = None,
        importance: str = "normal",
        tags: list[str] | None = None,
        tasks: list[str] | None = None,
        related: list[str] | None = None,
        links: list[str] | None = None,
        shelf: str | None = None,
    ) -> dict:
        """Record a decision, rule, fact, idea, bug, note or warning as soon as it is settled, without
        being asked. shelf files it on the shelf of knowledge it belongs to (a name or path,
        project shelf or shared tree); without one, a likely shelf is suggested. related names records it relates to (DEC-003, a task, file:src/a.gd); tasks
        names the tasks it applies to; links adds typed links, each written "relationship
        target" ("caused_by DEC-002", "resolved_by PROJ-6"). Without tasks, it is linked to this
        session's task. Records its text names are linked too. A name that matches nothing is
        reported in not_linked, and the memory is still saved. possible_duplicates lists records
        of the same type with similar titles. Agent-created memory is unlocked and marked as
        agent-written. An idea is never a requirement. project="global" is for
        memory true in every project; global rules and decisions must be proposed with
        brain_create_proposal instead."""
        found, _ = pick(session, project, write=True)
        if found.kind == "global" and type in GLOBAL_PERSON_TYPES:
            raise ValueError(GLOBAL_RULE_MESSAGE.format(kind="create_memory"))
        named = sort_named(session, found.id, [*(related or []), *(tasks or [])])
        created = MemoryService(session).create(
            found.id,
            MemoryCreate(
                type=type,
                title=title,
                content=content,
                importance=importance,  # type: ignore[arg-type]
                tags=tags or [],
                task_ids=named.tasks,
                related=named.memories,
            ),
            actor=agent,
        )
        linked = link_written(
            session,
            found.id,
            f"memory:{created.id}",
            actor=agent,
            links=[*named.links, *(links or [])],
            session_task=None if created.tasks else working.current(session, found.id),
            not_linked=named.not_linked,
        )
        return {
            "created": created.human_id,
            "type": created.type,
            "title": created.title,
            "linked_to": [r.human_id for r in created.related],
            "tasks": [t.human_id for t in created.tasks],
            **file_on_shelf(session, found.id, created.id, f"{title} {content}", shelf),
            **linked,
            **possible_duplicates(session, found.id, created.id, created.type, created.title),
        }

    @tool(WRITE)
    def brain_link_memories(
        session: Session, memory: str, related: list[str], project: str | None = None
    ) -> dict:
        """Link a memory to other memories of the same project (IDs such as DEC-003), so a context
        pack that includes one brings the others. Links never change the records themselves."""
        if not related:
            raise ValueError("Give at least one memory ID to link to.")
        found, _ = pick(session, project, write=True)
        service = MemoryService(session)
        for ref in related:
            result = service.link(found.id, memory, ref, actor=agent)
        return {"memory": result.human_id, "linked_to": [r.human_id for r in result.related]}

    @tool(READ)
    def brain_links(session: Session, node: str | None = None, project: str | None = None) -> dict:
        """What a record connects to, and how. node is a human ID (PB-12, DEC-003) or kind:value
        (task:PB-12, memory:DEC-003, file:src/a.py, shelf:Inventory). Each link reads from that
        record: "uses", "used_by", "governed_by". Omit node to list the relationship types."""
        found, _ = pick(session, project)
        service = GraphService(session)
        if node is None:
            return {
                "relationships": [
                    {"name": r.name, "inverse": r.inverse, "group": r.group}
                    for r in service.relationship_types()
                ]
            }
        result = service.node_links(found.id, node)
        return {
            "node": f"{result.node.label}: {result.node.title}",
            "links": [
                {
                    "relationship": x.relationship,
                    "node": f"{x.node.kind}:{x.node.label}",
                    "title": x.node.title,
                    "strength": x.strength,
                    "confidence": x.confidence,
                    "status": x.status,
                    "why": "; ".join(p.get("detail", "") for p in x.provenance[-2:]),
                    "link_id": x.id,
                }
                for x in result.links
            ],
        }

    @tool(WRITE)
    def brain_link(
        session: Session,
        source: str,
        relationship: str,
        target: str,
        project: str | None = None,
        strength: float | None = None,
        note: str | None = None,
        remove: bool = False,
    ) -> dict:
        """Record how two records of one project relate, as a typed link: source relationship
        target, e.g. ("file:ui/grid.gd", "uses", "file:inventory_manager.gd") or ("BUG-004",
        "caused_by", "DEC-002"). Use brain_links without a node for the relationship types;
        negative ones (independent_of, must_not_depend_on) keep records apart. strength is 0-1:
        0.3 useful, 0.5 relevant, 0.7 strong, 0.9 critical. remove=true deletes the link; links a
        person made cannot be removed by an agent. Removing an inferred link rejects it so it
        is not proposed again; asserting a candidate link confirms it. Name a Global record as
        global:RULE-3 to route it into this project; another project's records cannot be
        linked."""
        found, _ = pick(session, project, write=True)
        service = GraphService(session)
        if remove:
            existing = service.find_link(found.id, source, relationship, target)
            if existing is None:
                raise ValueError("No stored link matches. Built-in links are removed where made.")
            if existing.created_by == "user":
                raise ValueError(
                    "A person made this link. Suggest removing it with brain_create_proposal."
                )
            service.unlink(found.id, existing.id, actor=agent)
            return {"removed": f"{source} {relationship} {target}"}
        edge = service.link(
            found.id,
            source,
            relationship,
            target,
            strength=strength,
            note=note,
            created_by="system",
            actor=agent,
        )
        read = service.link_read(found.id, edge)
        return {
            "linked": f"{source} {relationship} {target}",
            "stored_as": edge.relationship,
            "strength": edge.strength,
            "confidence": edge.confidence,
            "target": read.node.title,
        }

    @tool(READ)
    def brain_shelves(
        session: Session,
        project: str | None = None,
        shelf: str | None = None,
        task: str | None = None,
        text: str | None = None,
    ) -> dict:
        """Shelves: the tree of knowledge records are filed on, from broad to specific
        (Knowledge > Game development > Game design > Game mechanics). The shared tree is one
        for every project, and each project sees only its own records on it; a project may keep
        shelves of its own too. With shelf (a name or path), its records. With task or text, how
        strongly that work wakes each shelf."""
        found, _ = pick(session, project)
        service = ShelfService(session)
        if shelf is not None:
            chosen = service.find(found.id, shelf)
            nodes = service.memberships(chosen.project_id, [chosen], for_project=found.id)
            info = service.graph.describe(found.id, nodes[chosen.id])
            return {
                "shelf": service.path(chosen),
                "keywords": [k for k in chosen.keywords.split(",") if k],
                "members": sorted(f"{i.node.kind}:{i.label} {i.title}" for i in info.values()),
            }
        if task is not None or text is not None:
            activations = ContextService(session).shelf_activation(found.id, task=task, query=text)
            return {
                "activation": [
                    {
                        "shelf": a.path or a.name,
                        "shared": a.scope == "global",
                        "activation": a.activation,
                        "active": a.active,
                        "why": a.reason,
                    }
                    for a in activations
                    if a.activation > 0 or a.scope == "project"
                ]
            }
        own = service.list(found.id)
        shelves, members = service.shared(found.id)
        # In path order, so each shelf comes right after the one it sits on and the list reads
        # as the tree it is.
        return {
            "shared_tree": sorted(
                (
                    {"shelf": service.path(s), "records": len(members.get(s.id, ())), "keywords": k}
                    for s in shelves
                    for k in [[w for w in s.keywords.split(",") if w]]
                ),
                key=lambda row: [part.casefold() for part in row["shelf"].split(" > ")],
            ),
            "project_shelves": sorted(
                (
                    {
                        "shelf": service.path(service.get(found.id, s.id)),
                        "keywords": s.keywords,
                        "records": s.member_count,
                    }
                    for s in own
                ),
                key=lambda row: [part.casefold() for part in row["shelf"].split(" > ")],
            ),
        }

    @tool(WRITE)
    def brain_update_shelf(
        session: Session,
        shelf: str,
        project: str | None = None,
        shared: bool = False,
        keywords: list[str] | None = None,
        description: str | None = None,
        parent: str | None = None,
        add: list[str] | None = None,
        remove: list[str] | None = None,
        delete: bool = False,
    ) -> dict:
        """File records on a shelf, or create or change one. shelf is a name or a path
        ("Knowledge > Software engineering > Frontend"); a missing shelf along a path is
        created. shared puts a new shelf on the shared tree every project uses (prefer it:
        categories are knowledge, not projects); otherwise a named shelf is looked up in the
        project, then the shared tree. add and remove take the project's records (human IDs or
        kind:value), which stay in their project. delete removes the shelf, never its records.
        Tagging a record with a shelf's name also puts it on the shelf."""
        found, _ = pick(session, project, write=True)
        service = ShelfService(session)
        home = GLOBAL_PROJECT_ID if shared else found.id
        try:
            chosen = service.get(home, shelf) if shared else service.find(found.id, shelf)
            if (
                ">" in shelf
                and service.path(chosen).casefold()
                != " > ".join(n.strip() for n in shelf.split(">")).casefold()
            ):
                chosen = service.ensure_path(home, shelf, keywords=keywords, actor=agent)
        except HTTPException:
            chosen = service.ensure_path(home, shelf, keywords=keywords, actor=agent)
        if delete:
            path = service.path(chosen)
            service.delete(chosen.project_id, chosen.id, actor=agent)
            return {"deleted": path}
        changes = {
            k: v
            for k, v in {"keywords": keywords, "description": description, "parent": parent}.items()
            if v is not None
        }
        if changes:
            service.update(chosen.project_id, chosen.id, ShelfUpdate(**changes), actor=agent)
        if add:
            service.place(found.id, chosen.id, add, actor=agent)
        if remove:
            service.place(found.id, chosen.id, remove, remove=True, actor=agent)
        nodes = service.memberships(chosen.project_id, [chosen], for_project=found.id)
        return {
            "shelf": service.path(chosen),
            "shared": chosen.project_id == GLOBAL_PROJECT_ID,
            "keywords": [k for k in chosen.keywords.split(",") if k],
            "records": len(nodes[chosen.id]),
        }

    @tool(WRITE)
    def brain_update_memory(
        session: Session,
        memory: str,
        project: str | None = None,
        title: str | None = None,
        content: str | None = None,
        importance: str | None = None,
        tags: list[str] | None = None,
        resolved: bool | None = None,
        links: list[str] | None = None,
    ) -> dict:
        """Edit an unlocked memory. Locked memory is refused: propose the change instead.

        Set resolved on a known issue (type bug) to mark it resolved or pending again. links adds
        typed links, each written "relationship target" ("resolved_by PROJ-6"); links describe a
        record without changing it, so they can be added to locked memory too. Records the new
        text names are linked.
        """
        found, _ = pick(session, project, write=True)
        changes = {
            k: v
            for k, v in dict(
                title=title,
                content=content,
                importance=importance,
                tags=tags,
                is_resolved=resolved,
            ).items()
            if v is not None
        }
        if not changes and not links:
            raise ValueError("Give at least one field to change.")
        service = MemoryService(session)
        record = service.get(found.id, memory)
        if changes:
            refuse_global_rule(found, record)
            updated = service.update(
                found.id, memory, MemoryUpdate.model_validate(changes), actor=agent
            )
        else:
            updated = service.read(found.id, record.id)
        return {
            "updated": updated.human_id,
            "title": updated.title,
            **link_written(
                session, found.id, f"memory:{updated.id}", actor=agent, links=links or []
            ),
        }

    @tool(WRITE)
    def brain_supersede_memory(
        session: Session,
        memory: str,
        title: str,
        content: str = "",
        project: str | None = None,
        links: list[str] | None = None,
    ) -> dict:
        """Replace an unlocked memory with a newer one. The old one is kept as history, and the
        new one keeps its links. links adds typed links, each written "relationship target"."""
        found, _ = pick(session, project, write=True)
        service = MemoryService(session)
        refuse_global_rule(found, service.get(found.id, memory))
        new = service.supersede(
            found.id, memory, MemorySupersede(title=title, content=content), actor=agent
        )
        return {
            "created": new.human_id,
            "replaces": memory,
            **link_written(
                session,
                found.id,
                f"memory:{new.id}",
                actor=agent,
                links=links or [],
                session_task=None if new.tasks else working.current(session, found.id),
            ),
        }

    @tool(WRITE)
    def brain_create_proposal(
        session: Session,
        proposal_type: str,
        reason: str,
        target: str | None = None,
        payload: dict[str, Any] | None = None,
        project: str | None = None,
    ) -> dict:
        """Suggest a change for a person to review: create_memory, update_memory, supersede_memory,
        update_task, add_acceptance_criterion, associate_file, or create_bug. Use this for locked
        memory and global rules. Nothing changes until it is accepted. A finished task goes to
        the person with brain_submit_review instead."""
        found, _ = pick(session, project, write=True)
        if proposal_type == "complete_task" and target:
            moved = TaskService(session).update(found.id, target, TaskUpdate(status="review"))
            reported = ReviewService(session).submitted_review(moved.id) is not None
            return {
                "applied": False,
                "status": moved.status,
                "message": f"{moved.human_id} waits in the person's Review screen."
                if reported
                else REVIEW_DRAFTED.format(task=moved.human_id),
            }
        p = ProposalService(session).create(
            found.id,
            ProposalCreate(
                proposal_type=proposal_type,
                target=target,
                payload=payload or {},  # type: ignore[arg-type]
                reason=reason,
            ),
            agent=agent,
        )
        return {
            "proposal": p.human_id,
            "status": p.status,
            "changes": p.changes,
            "message": "Recorded. A person will review it in Project Moah.",
        }

    return server


if __name__ == "__main__":  # `python -m app.mcp.server`, as source installs were connected
    raise SystemExit(main())

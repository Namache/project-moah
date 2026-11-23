"""Questions an agent asks in the chat, caught by the agent's own hooks, so they wait in Review.

Agents ask the person in the chat rather than calling brain_ask_person (three real runs: never
once). Claude Code and Codex run three hooks that Connect installs:

- ``project-moah-mcp --hook stop`` when the agent ends its turn. When the turn ends on a question
  and the session's task is still open, the question is recorded as if the agent had asked with
  brain_ask_person: the task moves to Blocked and the question waits at the top of Review. Not
  when the same chat already asked through Moah in that turn. Claude Code's Stop hook then waits
  for the person's answer in Review and wakes the chat with it (services/chat_wait.py).
- ``project-moah-mcp --hook prompt`` when the person writes. A reply in the same chat settles
  every question that chat asked ("answered in the chat"), on whatever task it asked about, so
  Review never keeps one the agent already has an answer to. While the session has no task yet,
  a message that names a task by ID, or plainly matches one task's title, gives the session that
  task: agents often ask before they pick a task. It also hands the chat what the person decided
  in Review and no waiter handed over yet (services/chat_delivery.py, ``prompt_delivery``).
- ``project-moah-mcp --hook tool`` after a Moah tool call (``mcp__project-moah__*`` or the
  desktop app's ``mcp__project-brain__*``). The agent gives its hook the chat's session id
  whichever MCP server ran the tool, which the desktop app's shared server never knows: so the
  hook records the task the call names as the session's task, and stamps the question or report
  the call wrote with the chat that wrote it (``TaskReview.session_id``).

Nothing is caught without a task, or once the task is in Review ("Want me to add tests too?"
after a hand-over is an offer, not a question for Review). Once the person closed the task (they
accepted it, and the agent still asks: push it? release it?), the question waits in a follow-up
task Moah starts for it, and the session goes on in that task. Only ids and times are stored for
the session; the question and the reply are stored on the review, like any other.

Every hook prints nothing on standard output, except Codex's prompt hook handing over a decision
(plain output of that hook is added to the model's context): Claude Code adds a hook's output to
the person's message, and Codex rejects output that is not JSON. A decision for Claude Code's chat
goes to standard error with exit code 2, the one exit code that wakes it.
"""

from __future__ import annotations

import re
import traceback
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import error_log
from app.mcp.projects import ProjectChoiceError, resolve_project
from app.models.agent_session import AgentSessionEvent
from app.models.project import Project
from app.models.review import TaskReview
from app.models.task import Task
from app.schemas.review import (
    DETAILS_LIMIT,
    OPTION_LIMIT,
    OPTIONS_LIMIT,
    SUMMARY_LIMIT,
    AskPerson,
    ReviewDecision,
)
from app.services.activity import acting_as
from app.services.agent_sessions import APP, HOOK_TASK, PROMPT, TASK, WAITING
from app.services.chat_delivery import is_delivery, is_task_notification
from app.services.hook_text import (
    REVIEW_TOOLS,
    asks,
    moah_tool,
    question_parts,
    stop_message,
    tool_arguments,
    tool_outcome,
    valid_id,
)
from app.services.reviews import ANSWERED_IN_CHAT, CLOSED, QUESTION_STATUS, ReviewService
from app.services.tasks import HUMAN_ID_PATTERN, TaskService
from app.services.words import REF_PATTERN

ASKABLE = ("backlog", "todo", "in_progress", "blocked")
# Where a message the person wrote may find its task: open work, not what is waiting or done.
PROMPT_STATUSES = ("backlog", "todo", "in_progress", "blocked", "review")
REPLY_LIMIT = 4000
# The tool hook runs right after the tool call, so the question or report the call wrote is this
# fresh. An older one waiting on the same task is not this call's.
STAMP_WINDOW = timedelta(minutes=2)
LIST_ITEM = re.compile(r"^\s*(?:[-*\u2022]|\d{1,2}[.)]|[a-fA-F][.)])\s+(.+?)\s*$")


# ---- reading the agent's message ----------------------------------------------------------


def _options(question: str) -> list[str]:
    """Short choices listed right under the question ("Which one? - A - B"), for the Review
    screen's answer buttons. Lines that are questions themselves are not choices."""
    lines = question.splitlines()
    for index, line in enumerate(lines):
        if not asks(line) or LIST_ITEM.match(line):
            continue
        items = []
        for item in lines[index + 1 :]:
            found = LIST_ITEM.match(item)
            if found is None:
                break
            items.append(found[1].strip("*_ "))
        if 2 <= len(items) <= OPTIONS_LIMIT and not any(
            asks(item) or len(item) > OPTION_LIMIT for item in items
        ):
            return items
    return []


def question_in(message: str | None) -> tuple[str, str | None, list[str]] | None:
    """The question a message ends on (hook_text.question_parts), what came before it, and any
    choices it lists, cut to what Review stores. None when it does not end on a question."""
    found = question_parts(message)
    if found is None:
        return None
    paragraphs, start = found
    asked = paragraphs[start:]
    # Keep the question short enough for Review's question box; the rest goes with the context.
    while len(asked) > 1 and len("\n\n".join(asked)) > SUMMARY_LIMIT:
        start += 1
        asked = asked[1:]
    question = "\n\n".join(asked)
    if len(question) > SUMMARY_LIMIT:
        question = "\u2026" + question[-(SUMMARY_LIMIT - 1) :]
    context = "\n\n".join(paragraphs[:start])[:DETAILS_LIMIT] or None
    return question, context, _options(question)


# ---- the session and its task -------------------------------------------------------------


def _aware(at: datetime) -> datetime:
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def _newest(session: Session, agent: str, session_id: str, *conditions) -> AgentSessionEvent | None:
    return session.scalars(
        select(AgentSessionEvent)
        .where(
            AgentSessionEvent.agent == agent,
            AgentSessionEvent.session_id == session_id,
            *conditions,
        )
        .order_by(AgentSessionEvent.created_at.desc(), AgentSessionEvent.id.desc())
        .limit(1)
    ).first()


def session_task(session: Session, agent: str, session_id: str) -> Task | None:
    """The task the session works on: the newest one its MCP server recorded, or that a message
    from the person named before the agent picked one."""
    event = _newest(
        session,
        agent,
        session_id,
        AgentSessionEvent.task_id.is_not(None),
        AgentSessionEvent.source.in_((TASK, HOOK_TASK, PROMPT)),
    )
    return session.get(Task, event.task_id) if event is not None else None


def _turn_started(session: Session, agent: str, session_id: str) -> datetime | None:
    event = _newest(session, agent, session_id, AgentSessionEvent.source == PROMPT)
    return _aware(event.created_at) if event is not None else None


def _project(session: Session, agent: str, session_id: str, cwd: object) -> Project | None:
    event = _newest(
        session,
        agent,
        session_id,
        AgentSessionEvent.project_id.is_not(None),
        AgentSessionEvent.source.not_in((PROMPT, WAITING, APP)),
    )
    if event is not None:
        return session.get(Project, event.project_id)
    try:
        found, _ = resolve_project(session, None, cwd if isinstance(cwd, str) and cwd else None)
    except ProjectChoiceError:
        return None
    return found if found.kind != "global" else None


def named_task(session: Session, project: Project, message: str) -> Task | None:
    """The open task the person's message names by ID, or the one task whose title and tags
    plainly match it, as context packs choose (services/context.py infer_task)."""
    from app.services.context import ContextService

    inferred = ContextService(session).infer_task(
        project, message, statuses=PROMPT_STATUSES, brief_fallback=False
    )
    return session.get(Task, inferred[0]) if inferred else None


def id_named(session: Session, project: Project, message: str) -> Task | None:
    """The one open task of ``project`` the message names by ID, or None when it names none or
    several (a message comparing two tasks says nothing about which one comes next)."""
    from app.services.context import ContextService
    from app.services.tasks import CLOSED_STATUSES

    finder = ContextService(session)
    found = {
        task.id: task
        for ref in REF_PATTERN.findall(message)
        if (task := finder.task_by_ref(project.id, ref)) is not None
        and task.status not in CLOSED_STATUSES
    }
    return next(iter(found.values())) if len(found) == 1 else None


def _actor(agent: str) -> tuple[str, str]:
    """Who the question is from, the way the MCP server attributes the agent's own calls."""
    return (agent if agent in ("claude", "codex") else "system", agent)


# ---- the three hooks ----------------------------------------------------------------------


def _asked_this_turn(session: Session, session_id: str, since: datetime | None) -> bool:
    """Whether this chat has a question waiting in Review, on any task, that it asked since its
    turn began (``since`` empty: no message of the person's was seen, so any). It asked through
    Moah this turn: its closing question in the chat repeats that, and is no new one."""
    asked = session.scalars(
        select(TaskReview.created_at).where(
            TaskReview.session_id == session_id,
            TaskReview.kind == "question",
            TaskReview.status == "pending",
        )
    )
    return any(since is None or _aware(at) >= since for at in asked)


def record_stop(
    session: Session, agent: str, hook_input: Mapping[str, object]
) -> TaskReview | None:
    """Record the question an agent's turn ended on, for the session's open task."""
    session_id = valid_id(hook_input.get("session_id"))
    found = question_in(stop_message(dict(hook_input)))
    if session_id is None or found is None:
        return None
    started = _turn_started(session, agent, session_id)
    if _asked_this_turn(session, session_id, started):
        return None
    question, context, options = found
    task = session_task(session, agent, session_id)
    reviews = ReviewService(session)
    if task is not None and task.status in CLOSED:
        with acting_as(*_actor(agent)):
            task, _ = reviews.follow_up(task, agent)
        # The session goes on in the follow-up: the person's reply settles the question there.
        session.add(
            AgentSessionEvent(
                agent=agent,
                session_id=session_id,
                project_id=task.project_id,
                task_id=task.id,
                source=HOOK_TASK,
                created_at=datetime.now(UTC),
            )
        )
        session.commit()
    if task is None or task.status not in ASKABLE:
        return None
    waiting = reviews.asked_question(task.id)
    if waiting is not None:
        # The agent asked with brain_ask_person in this turn (its own words are better), or
        # this is the question already waiting.
        if waiting.summary == question or started is None or _aware(waiting.created_at) >= started:
            return None
    payload = AskPerson(question=question, context=context, options=options)
    with acting_as(*_actor(agent)):
        return reviews.ask(task.project_id, task.id, payload, agent, session_id=session_id)


def _answer_in_chat(session: Session, session_id: str, task: Task | None, reply: str) -> None:
    """The person replied in this chat: settle every question this chat asked, whatever task it
    is about (an orchestrator asks about its sub-tasks), with the reply. Questions only: the
    ones an agent asked, a note of its that waits for the person included; a report waits for a
    decision, and a chat message is none. Never a question another chat asked.

    A question from before reviews remembered their chat (no session id) is settled only when it
    waits on this session's own task, as it was before."""
    reviews = ReviewService(session)
    waiting = list(
        dict.fromkeys(
            session.scalars(
                select(TaskReview.task_id).where(
                    TaskReview.session_id == session_id,
                    TaskReview.kind == "question",
                    TaskReview.status == "pending",
                )
            )
        )
    )
    if task is not None and task.id not in waiting:
        unstamped = reviews.asked_question(task.id)
        if unstamped is not None and unstamped.session_id is None:
            waiting.append(task.id)
    for task_id in waiting:
        about = session.get(Task, task_id)
        if about is None or about.status != QUESTION_STATUS:
            continue
        # Each decision commits on its own (it ends in TaskService.update), so rolling back after
        # a failure only undoes that question's unsaved changes, never one settled before it.
        try:
            with acting_as("human"):
                reviews.decide(
                    about.project_id,
                    about.id,
                    ReviewDecision(verdict="answer", comment=reply),
                    answered_in=ANSWERED_IN_CHAT,
                )
        except Exception as error:  # noqa: BLE001 - the other questions and the turn go on
            session.rollback()
            error_log.write("mcp", f"prompt hook: {type(error).__name__}", traceback.format_exc())


def record_prompt(session: Session, agent: str, hook_input: Mapping[str, object]) -> None:
    """The person wrote in the chat: settle the questions this chat asked, and remember the
    turn (and, while the session has no task, the task the message names)."""
    session_id = valid_id(hook_input.get("session_id"))
    if session_id is None:
        return
    prompt = hook_input.get("prompt")
    prompt = prompt.strip() if isinstance(prompt, str) else ""
    # Two kinds of message are not the person's reply: what Moah hands a chat (services/
    # chat_delivery.py; Codex's queue sends it as a message), and what Claude Code sends by itself
    # (a task notification: a background task finished, or a hook, Moah's or any other, woke the
    # chat). Neither settles a question or names a task. Both do start a turn.
    handed_over = is_delivery(prompt) or is_task_notification(prompt)
    task = session_task(session, agent, session_id)
    if prompt and not handed_over:
        reply = prompt if len(prompt) <= REPLY_LIMIT else prompt[: REPLY_LIMIT - 1] + "…"
        _answer_in_chat(session, session_id, task, reply)
    project = _project(session, agent, session_id, hook_input.get("cwd"))
    named = None
    if project and prompt and not handed_over:
        # No task yet: the task the message names or plainly matches. Already on a task: only
        # another open task the message names by ID ("now do HAB-5") moves the session there,
        # so the agent's next notes and checkpoint land on the work the person asked for.
        named = (
            named_task(session, project, prompt)
            if task is None
            else id_named(session, project, prompt)
        )
        if named is not None and task is not None and named.id == task.id:
            named = None
    session.add(
        AgentSessionEvent(
            agent=agent,
            session_id=session_id,
            project_id=project.id if project else None,
            task_id=named.id if named else None,
            source=PROMPT,
            created_at=datetime.now(UTC),
        )
    )
    session.commit()


def _ref(value: object) -> str | None:
    """A task a tool call names: its ID (CAMP-037) or its internal id."""
    text = value.strip() if isinstance(value, str) else ""
    return text if 0 < len(text) <= 64 else None


def _called_task_ref(
    tool: str, arguments: Mapping[str, object], outcome: Mapping[str, object]
) -> str | None:
    """The task a Moah tool call made the session's task, as the MCP server would have set it
    (mcp/tools/*.py, ``working.set``), by the ID the call or its result names. The result goes
    first where the server picks the task itself: a question about a closed task waits in its
    follow-up, a checkpoint without a task names the session's own."""
    named = _ref(arguments.get("task"))
    if tool == "brain_ask_person":
        return _ref(outcome.get("asked")) or named
    if tool == "brain_submit_review":
        return _ref(outcome.get("submitted")) or named
    if tool == "brain_create_checkpoint":
        # The result says which task the note went to, or none (then there is nothing to name).
        return _ref(outcome.get("task")) if "created" in outcome else named
    if tool == "brain_context_pack":
        return named
    if tool == "brain_create_task":
        # Only a task started in progress becomes the session's, and only its result names it.
        return _ref(outcome.get("created")) if outcome.get("status") == "in_progress" else None
    # brain_update_task: setting a task in progress makes it the session's.
    if arguments.get("status") != "in_progress" or outcome.get("applied") is False:
        return None
    if outcome.get("status", "in_progress") != "in_progress":
        return None
    return _ref(outcome.get("task")) or named


def _called_task(
    session: Session, agent: str, session_id: str, project: object, cwd: object, ref: str
) -> Task | None:
    """The task a tool call named, found as the server would: in the project the call names, else
    the session's own project. The desktop app's shared server runs in no folder, so when neither
    has it, the one task anywhere with that ID; never a guess between two."""
    projects: list[Project] = []
    if name := _ref(project):
        try:
            projects.append(resolve_project(session, name, None)[0])
        except ProjectChoiceError:
            pass
    own = _project(session, agent, session_id, cwd)
    if own is not None and all(own.id != found.id for found in projects):
        projects.append(own)
    for found in projects:
        try:
            return TaskService(session).get(found.id, ref)
        except Exception:  # noqa: BLE001 - not a task of this project
            continue
    if HUMAN_ID_PATTERN.fullmatch(ref):
        matches = session.scalars(
            select(Task).where(func.upper(Task.human_id) == ref.upper()).limit(2)
        ).all()
    else:
        matches = [task] if (task := session.get(Task, ref)) is not None else []
    return matches[0] if len(matches) == 1 else None


def record_tool(session: Session, agent: str, hook_input: Mapping[str, object]) -> None:
    """A Moah tool ran in this chat (PostToolUse): remember the task it names as the session's
    task, and stamp the question or report it wrote with this chat's session id.

    Works for either MCP server, as the agent hands its hook the chat's id whichever one ran the
    tool. A call that failed, or that names no task the MCP server would take up as the session's
    (see _called_task_ref), records nothing. Only the tools that write to Review stamp, and only
    a round written moments ago that no chat claimed yet. The hook runs the code installed now;
    an MCP server already running keeps its old code."""
    session_id = valid_id(hook_input.get("session_id"))
    tool = moah_tool(hook_input.get("tool_name"))
    outcome = tool_outcome(hook_input.get("tool_response"))
    if session_id is None or tool is None or outcome is None:
        return
    arguments = tool_arguments(hook_input.get("tool_input"))
    ref = _called_task_ref(tool, arguments, outcome)
    task = (
        _called_task(
            session, agent, session_id, arguments.get("project"), hook_input.get("cwd"), ref
        )
        if ref is not None
        else None
    )
    if task is None:
        return
    newest = _newest(
        session,
        agent,
        session_id,
        AgentSessionEvent.source.in_((TASK, HOOK_TASK)),
        AgentSessionEvent.project_id == task.project_id,
    )
    # As SessionTracker.record_tasks: nothing when the server (or this hook) already has it.
    if newest is None or newest.task_id != task.id:
        session.add(
            AgentSessionEvent(
                agent=agent,
                session_id=session_id,
                project_id=task.project_id,
                task_id=task.id,
                source=HOOK_TASK,
                created_at=datetime.now(UTC),
            )
        )
    if tool in REVIEW_TOOLS:
        # The newest round, when this call just wrote it and nothing stamped it yet.
        review = session.scalars(
            select(TaskReview)
            .where(TaskReview.task_id == task.id, TaskReview.status == "pending")
            .order_by(TaskReview.round.desc())
            .limit(1)
        ).first()
        if (
            review is not None
            and review.session_id is None
            and _aware(review.created_at) >= datetime.now(UTC) - STAMP_WINDOW
        ):
            review.session_id = session_id
    session.commit()


HOOKS = {"stop": record_stop, "prompt": record_prompt, "tool": record_tool}

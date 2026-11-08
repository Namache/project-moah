"""Questions an agent asks in the chat, caught by the agent's own hooks, so they wait in Review.

Agents ask the person in the chat rather than calling brain_ask_person (three real runs: never
once). Claude Code and Codex run two hooks that Connect installs:

- ``project-moah-mcp --hook stop`` when the agent ends its turn. When the turn ends on a question
  and the session's task is still open, the question is recorded as if the agent had asked with
  brain_ask_person: the task moves to Blocked and the question waits at the top of Review.
- ``project-moah-mcp --hook prompt`` when the person writes. A reply in the same chat settles the
  question ("answered in the chat"), so Review never keeps one the agent already has an answer
  to. While the session has no task yet, a message that names a task by ID, or plainly matches
  one task's title, gives the session that task: agents often ask before they pick a task.

Nothing is caught without a task, or once the task is in Review ("Want me to add tests too?"
after a hand-over is an offer, not a question for Review). Once the person closed the task (they
accepted it, and the agent still asks: push it? release it?), the question waits in a follow-up
task Moah starts for it, and the session goes on in that task. Only ids and times are stored for
the session; the question and the reply are stored on the review, like any other.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

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
from app.services.agent_sessions import TASK
from app.services.hook_text import asks, question_parts, stop_message, valid_id
from app.services.reviews import ANSWERED_IN_CHAT, CLOSED, QUESTION_STATUS, ReviewService

PROMPT = "prompt"  # agent_session_events.source for a message the person wrote
ASKABLE = ("backlog", "todo", "in_progress", "blocked")
# Where a message the person wrote may find its task: open work, not what is waiting or done.
PROMPT_STATUSES = ("backlog", "todo", "in_progress", "blocked", "review")
REPLY_LIMIT = 4000
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
        AgentSessionEvent.source.in_((TASK, PROMPT)),
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
        AgentSessionEvent.source != PROMPT,
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
    plainly match it, as context packs choose (services/context.py _infer_task)."""
    from app.services.context import ContextService

    inferred = ContextService(session)._infer_task(
        project, message, statuses=PROMPT_STATUSES, brief_fallback=False
    )
    return session.get(Task, inferred[0]) if inferred else None


def _actor(agent: str) -> tuple[str, str]:
    """Who the question is from, the way the MCP server attributes the agent's own calls."""
    return (agent if agent in ("claude", "codex") else "system", agent)


# ---- the two hooks ------------------------------------------------------------------------


def record_stop(
    session: Session, agent: str, hook_input: Mapping[str, object]
) -> TaskReview | None:
    """Record the question an agent's turn ended on, for the session's open task."""
    session_id = valid_id(hook_input.get("session_id"))
    found = question_in(stop_message(dict(hook_input)))
    if session_id is None or found is None:
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
                source=TASK,
                created_at=datetime.now(UTC),
            )
        )
        session.commit()
    if task is None or task.status not in ASKABLE:
        return None
    waiting = reviews.asked_question(task.id)
    if waiting is not None:
        started = _turn_started(session, agent, session_id)
        # The agent asked with brain_ask_person in this turn (its own words are better), or
        # this is the question already waiting.
        if waiting.summary == question or started is None or _aware(waiting.created_at) >= started:
            return None
    payload = AskPerson(question=question, context=context, options=options)
    with acting_as(*_actor(agent)):
        return reviews.ask(task.project_id, task.id, payload, agent)


def record_prompt(session: Session, agent: str, hook_input: Mapping[str, object]) -> None:
    """The person wrote in the chat: settle the question waiting for this session's task, and
    remember the turn (and, while the session has no task, the task the message names)."""
    session_id = valid_id(hook_input.get("session_id"))
    if session_id is None:
        return
    prompt = hook_input.get("prompt")
    prompt = prompt.strip() if isinstance(prompt, str) else ""
    task = session_task(session, agent, session_id)
    if task is not None and prompt and task.status == QUESTION_STATUS:
        reviews = ReviewService(session)
        if reviews.asked_question(task.id) is not None:
            reply = prompt if len(prompt) <= REPLY_LIMIT else prompt[: REPLY_LIMIT - 1] + "…"
            with acting_as("human"):
                reviews.decide(
                    task.project_id,
                    task.id,
                    ReviewDecision(verdict="answer", comment=reply),
                    answered_in=ANSWERED_IN_CHAT,
                )
    project = _project(session, agent, session_id, hook_input.get("cwd"))
    named = named_task(session, project, prompt) if task is None and project and prompt else None
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


HOOKS = {"stop": record_stop, "prompt": record_prompt}

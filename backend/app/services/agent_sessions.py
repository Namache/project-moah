"""Which agent session worked on which task, by the agent's own session id.

Claude Code names each log file after its session id and tells hooks and MCP servers that id, so
token use read from the logs (services/usage.py) can be matched to tasks exactly, instead of by
time windows. Two writers:

- The SessionStart hook (``project-moah-mcp --brief``) records the session id it is given on
  standard input, with the project, at startup, /clear, /compact and resume.
- The MCP server records the session's task whenever it changes. It learns its session id from
  CLAUDE_CODE_SESSION_ID (set by Claude Code when it starts the server) and follows /clear,
  which starts a new session id in the same Claude Code process, through the hook's records of
  that process. A server that gets no id (a sandboxed Flatpak started by an agent setup written
  before the id was passed as an argument) takes over the one session the hook saw start in its
  project at the same time, and claims it, so no other server takes it too.

- The prompt hook (``project-moah-mcp --hook prompt``, services/chat_questions.py) records each
  message the person writes, by time only, and while the session has no task yet, the task the
  message names.

Only ids, times and the hook's source are kept.
"""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.agent_session import AgentSessionEvent
from app.services.hook_text import read_hook_input  # noqa: F401 - where callers import it
from app.services.hook_text import valid_id as _id

SESSION_ENV = "CLAUDE_CODE_SESSION_ID"
PID_ENV = "CLAUDE_PID"
KEEP = timedelta(days=62)
TASK = "task"
PROMPT = "prompt"  # a message the person wrote (services/chat_questions.py)
CLAIM = "claimed"  # a server with no session id of its own took this session over
STARTS = ("startup", "resume", "clear")
# The hook and the MCP server start together, seconds apart; a session that started further
# away is not ours. Kept tight: with two minutes, a server whose own hook was recorded late
# took the session of a neighbour started a minute earlier, and that one then took its session.
# A server also waits until NEAR has passed before it adopts, so a neighbour started within
# NEAR is seen and makes the choice ambiguous instead of being taken.
NEAR = timedelta(seconds=15)
# How long a server without an id keeps looking (the hook may run after the first tool call).
LOOK = timedelta(minutes=30)


def record_start(
    session: Session,
    agent: str,
    hook_input: Mapping[str, object],
    project_id: str | None,
    environ: Mapping[str, str] = os.environ,
) -> AgentSessionEvent | None:
    """Store the session id a SessionStart hook was given. Nothing without a valid id."""
    session_id = _id(hook_input.get("session_id")) or _id(environ.get(SESSION_ENV))
    if session_id is None:
        return None
    source = hook_input.get("source")
    event = AgentSessionEvent(
        agent=agent,
        session_id=session_id,
        project_id=project_id,
        source=source[:16] if isinstance(source, str) and source else "startup",
        agent_pid=_id(environ.get(PID_ENV)),
        created_at=datetime.now(UTC),
    )
    session.add(event)
    session.execute(
        delete(AgentSessionEvent).where(AgentSessionEvent.created_at < event.created_at - KEEP)
    )
    session.commit()
    return event


class SessionTracker:
    """The MCP server's view of which agent session it serves, and the tasks it worked on."""

    def __init__(
        self,
        agent: str,
        environ: Mapping[str, str] = os.environ,
        now: datetime | None = None,
    ) -> None:
        self.agent = agent
        self.started = _id(environ.get(SESSION_ENV))
        self.current: str | None = self.started
        self.born = now or datetime.now(UTC)
        self._recorded: dict[tuple[str, str], str | None] = {}
        self._prompt_seen = 0  # the newest prompt-hook event already taken up

    def adopt(self, session: Session, project_id: str | None, now: datetime | None = None) -> bool:
        """For a server that got no session id: take over the session the hook saw start in the
        same project within NEAR of this server, when there is exactly one that no other server
        claimed, once NEAR has passed. With two or more, none: a wrong link is worse than no
        link. True when adopted."""
        if self.started is not None:
            return False
        now = now or datetime.now(UTC)
        if not self.born + NEAR <= now <= self.born + LOOK:
            return False
        claimed = select(AgentSessionEvent.session_id).where(
            AgentSessionEvent.agent == self.agent,
            AgentSessionEvent.source.in_((CLAIM, TASK)),
        )
        query = select(AgentSessionEvent.session_id).where(
            AgentSessionEvent.agent == self.agent,
            AgentSessionEvent.source.in_(STARTS),
            AgentSessionEvent.created_at.between(self.born - NEAR, self.born + NEAR),
            AgentSessionEvent.session_id.not_in(claimed),
        )
        if project_id is not None:
            query = query.where(AgentSessionEvent.project_id == project_id)
        found = set(session.scalars(query))
        if len(found) != 1:
            return False
        self.started = self.current = found.pop()
        session.add(
            AgentSessionEvent(
                agent=self.agent,
                session_id=self.started,
                project_id=project_id,
                source=CLAIM,
                created_at=now,
            )
        )
        session.commit()
        return True

    def refresh(
        self, session: Session, project_id: str | None = None, now: datetime | None = None
    ) -> bool:
        """Follow /clear: the newest session the hook saw in the same agent process, after the
        one this server was started for. Returns True when the session changed. A server with no
        session id first tries to adopt one (see adopt; project_id is its folder's project)."""
        if self.started is None and not self.adopt(session, project_id, now):
            return False
        first = session.scalars(
            select(AgentSessionEvent)
            .where(
                AgentSessionEvent.agent == self.agent,
                AgentSessionEvent.session_id == self.started,
                AgentSessionEvent.agent_pid.is_not(None),
            )
            .order_by(AgentSessionEvent.created_at)
            .limit(1)
        ).first()
        newest = self.started
        if first is not None:
            latest = session.scalars(
                select(AgentSessionEvent.session_id)
                .where(
                    AgentSessionEvent.agent == self.agent,
                    AgentSessionEvent.agent_pid == first.agent_pid,
                    AgentSessionEvent.source.not_in((TASK, CLAIM)),
                    AgentSessionEvent.created_at >= first.created_at,
                )
                .order_by(AgentSessionEvent.created_at.desc(), AgentSessionEvent.id.desc())
                .limit(1)
            ).first()
            newest = latest or self.started
        changed = newest != self.current
        self.current = newest
        return changed

    def named_by_person(self, session: Session) -> tuple[str, str] | None:
        """(project id, task id) of the task the person's newest message named, once per
        message, when the prompt hook saw it after this server last looked. The person's own
        words say what the work is now, so the session follows them: without this, an agent
        that never fetched a pack filed its checkpoint under an older task (2026-11-07 run)."""
        if self.current is None:
            return None
        event = session.scalars(
            select(AgentSessionEvent)
            .where(
                AgentSessionEvent.agent == self.agent,
                AgentSessionEvent.session_id == self.current,
                AgentSessionEvent.source == PROMPT,
                AgentSessionEvent.id > self._prompt_seen,
            )
            .order_by(AgentSessionEvent.id.desc())
            .limit(1)
        ).first()
        if event is None:
            return None
        self._prompt_seen = event.id
        if event.task_id is None or event.project_id is None:
            return None
        return event.project_id, event.task_id

    def record_tasks(self, session: Session, tasks: Mapping[str, str]) -> None:
        """Store each project's session task when it differs from the one last stored."""
        if self.current is None:
            return
        added = False
        for project_id, task_id in tasks.items():
            key = (self.current, project_id)
            if self._recorded.get(key) == task_id:
                continue
            self._recorded[key] = task_id
            session.add(
                AgentSessionEvent(
                    agent=self.agent,
                    session_id=self.current,
                    project_id=project_id,
                    task_id=task_id,
                    source=TASK,
                    created_at=datetime.now(UTC),
                )
            )
            added = True
        if added:
            session.commit()


def _aware(at: datetime) -> datetime:
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def session_tasks(
    session: Session, since: datetime, until: datetime
) -> dict[tuple[str, str], list[tuple[datetime, str]]]:
    """(agent, session id) -> [(time, task id)], oldest first, for task changes in the window."""
    found: dict[tuple[str, str], list[tuple[datetime, str]]] = defaultdict(list)
    for agent, session_id, task_id, at in session.execute(
        select(
            AgentSessionEvent.agent,
            AgentSessionEvent.session_id,
            AgentSessionEvent.task_id,
            AgentSessionEvent.created_at,
        ).where(
            AgentSessionEvent.task_id.is_not(None),
            # A task the person's message named (services/chat_questions.py) is a guess from
            # words, not what the session worked on: token use follows the MCP server's records.
            AgentSessionEvent.source == TASK,
            AgentSessionEvent.created_at.between(since, until),
        )
    ):
        found[(agent, session_id)].append((_aware(at), task_id))
    for items in found.values():
        items.sort()
    return found

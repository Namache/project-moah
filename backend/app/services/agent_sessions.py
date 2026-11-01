"""Which agent session worked on which task, by the agent's own session id.

Claude Code names each log file after its session id and tells hooks and MCP servers that id, so
token use read from the logs (services/usage.py) can be matched to tasks exactly, instead of by
time windows. Two writers:

- The SessionStart hook (``project-moah-mcp --brief``) records the session id it is given on
  standard input, with the project, at startup, /clear, /compact and resume.
- The MCP server records the session's task whenever it changes. It learns its session id from
  CLAUDE_CODE_SESSION_ID (set by Claude Code when it starts the server) and follows /clear,
  which starts a new session id in the same Claude Code process, through the hook's records of
  that process.

Only ids, times and the hook's source are kept.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import IO

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.agent_session import AgentSessionEvent

SESSION_ENV = "CLAUDE_CODE_SESSION_ID"
PID_ENV = "CLAUDE_PID"
KEEP = timedelta(days=62)
TASK = "task"
VALID_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


def _id(value: object) -> str | None:
    return value if isinstance(value, str) and VALID_ID.match(value) else None


def read_hook_input(stream: IO[str] | None = None, timeout: float = 1.0) -> dict:
    """The JSON a Claude Code hook gets on standard input, or {} when there is none.

    Never blocks for long: run by hand or by another agent, standard input may stay open."""
    stream = stream if stream is not None else sys.stdin
    try:
        if stream is None or stream.isatty():
            return {}
    except (OSError, ValueError):
        return {}
    box: list[str] = []

    def read() -> None:
        try:
            box.append(stream.read(1 << 16))
        except (OSError, ValueError):
            pass

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(timeout)
    if not box:
        return {}
    try:
        data = json.loads(box[0])
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


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

    def __init__(self, agent: str, environ: Mapping[str, str] = os.environ) -> None:
        self.agent = agent
        self.started = _id(environ.get(SESSION_ENV))
        self.current: str | None = self.started
        self._recorded: dict[tuple[str, str], str | None] = {}

    def refresh(self, session: Session) -> bool:
        """Follow /clear: the newest session the hook saw in the same agent process, after the
        one this server was started for. Returns True when the session changed."""
        if self.started is None:
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
                    AgentSessionEvent.source != TASK,
                    AgentSessionEvent.created_at >= first.created_at,
                )
                .order_by(AgentSessionEvent.created_at.desc(), AgentSessionEvent.id.desc())
                .limit(1)
            ).first()
            newest = latest or self.started
        changed = newest != self.current
        self.current = newest
        return changed

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
            AgentSessionEvent.created_at.between(since, until),
        )
    ):
        found[(agent, session_id)].append((_aware(at), task_id))
    for items in found.values():
        items.sort()
    return found


def session_projects(session: Session, since: datetime) -> dict[tuple[str, str], str]:
    """(agent, session id) -> the project its hook or tasks named last."""
    rows = session.execute(
        select(AgentSessionEvent.agent, AgentSessionEvent.session_id, AgentSessionEvent.project_id)
        .where(AgentSessionEvent.project_id.is_not(None), AgentSessionEvent.created_at >= since)
        .order_by(AgentSessionEvent.created_at)
    )
    return {(agent, sid): pid for agent, sid, pid in rows}

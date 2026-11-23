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
- The tool hook (``--hook tool``, the same module) records the session's task as a Moah tool call
  names it (source ``hook_task``), so a chat is known even when its MCP server was never told its
  session id (the desktop app's shared server).

- Review's button (``app_chat``, below) finds the Claude desktop app's own id for a chat once and
  keeps it (source ``app``), so the next look does not read the app's files again.

Only ids, times and the hook's source are kept.
"""

from __future__ import annotations

import os
import threading
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.agent_session import AgentSessionEvent
from app.services import claude_desktop
from app.services.hook_text import read_hook_input  # noqa: F401 - where callers import it
from app.services.hook_text import valid_id as _id

SESSION_ENV = "CLAUDE_CODE_SESSION_ID"
PID_ENV = "CLAUDE_PID"
KEEP = timedelta(days=62)
TASK = "task"
# The session's task as an agent's hook recorded it (services/chat_questions.py: the tool hook, and
# the follow-up a Stop hook starts). Counts as the session's task and for token use, but is not a
# server's claim: a server with no session id may still adopt a chat a hook already saw work.
HOOK_TASK = "hook_task"
PROMPT = "prompt"  # a message the person wrote (services/chat_questions.py)
# A Stop hook is waiting for the person's answer in Review for this chat (services/chat_wait.py).
# A newer row for the same chat supersedes the older waiter. Not a task, a claim or a new session:
# no reader of the session's task, adoption, /clear or token use looks at it.
WAITING = "waiting"
# The Claude desktop app's own id for this chat (``app_session``), found once by app_chat. Like
# WAITING it is not a task, a claim or a new session: the readers of those use lists of the
# sources they want, and the two that list the ones they do not (SessionTracker.refresh,
# chat_questions._project) name APP.
APP = "app"
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
# A decision the person gives in Review goes to the chat that worked on the task, when the review
# itself does not know its chat: only a chat that touched the task this recently counts.
WORKED = timedelta(hours=48)


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
        if project_id is None:
            # No folder project: a desktop app's server, which its chats share. Matching by
            # time alone would take over a terminal session that started at the same moment.
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
                    AgentSessionEvent.source.not_in((TASK, CLAIM, HOOK_TASK, WAITING, APP)),
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


def chat_working_on(session: Session, task_id: str, now: datetime | None = None) -> str | None:
    """The session id of the chat that worked on the task most recently (within WORKED), as the
    MCP server or a hook recorded it, or None. None also when two chats touched it at the very
    same moment: a wrong chat gets someone else's answer, so none is better than a guess."""
    now = now or datetime.now(UTC)
    rows = session.execute(
        select(
            AgentSessionEvent.agent,
            AgentSessionEvent.session_id,
            func.max(AgentSessionEvent.created_at),
        )
        .where(
            AgentSessionEvent.task_id == task_id,
            AgentSessionEvent.source.in_((TASK, HOOK_TASK)),
            AgentSessionEvent.created_at >= now - WORKED,
        )
        .group_by(AgentSessionEvent.agent, AgentSessionEvent.session_id)
    ).all()
    if not rows:
        return None
    newest = max(at for _, _, at in rows)
    chats = {session_id for _, session_id, at in rows if at == newest}
    return chats.pop() if len(chats) == 1 else None


# What a search of the app's records found nothing for, kept in this process (not the database:
# it is only to spare the disk, and a restart may look again). Review's box asks for the chat when
# it shows and again a few seconds later, and a terminal chat would read up to 120 files each time.
# A chat the app takes up after a miss is found again once this time has passed.
MISS_FOR = timedelta(seconds=60)
_MISS_LIMIT = 256
_misses: dict[tuple[str, tuple[str, ...]], tuple[str, datetime]] = {}
_misses_lock = threading.Lock()


def forget_app_misses() -> None:
    """Drop what is remembered about searches that found nothing (for tests)."""
    with _misses_lock:
        _misses.clear()


def _miss_key(session_id: str, folders: Sequence[Path] | None) -> tuple[str, tuple[str, ...]]:
    return session_id, tuple(
        str(f) for f in (claude_desktop.config_folders() if folders is None else folders)
    )


def app_chat(
    session: Session,
    session_id: str,
    folders: Sequence[Path] | None = None,
    now: datetime | None = None,
) -> claude_desktop.Lookup:
    """The Claude desktop app's record of a Claude Code chat (see services/claude_desktop.py).

    A record found is kept as an ``app`` row, and used next time after a look at its one file:
    if the file is gone or archived, or no longer runs this session, the row is dropped and the
    app's records are searched again. A search that finds nothing, or cannot read, is remembered
    in memory for MISS_FOR (not in the database), so a chat the app takes up later is found within
    a minute."""
    now = now or datetime.now(UTC)
    kept = session.scalars(
        select(AgentSessionEvent)
        .where(
            AgentSessionEvent.agent == "claude",
            AgentSessionEvent.session_id == session_id,
            AgentSessionEvent.source == APP,
            AgentSessionEvent.app_session.is_not(None),
        )
        .order_by(AgentSessionEvent.created_at.desc(), AgentSessionEvent.id.desc())
        .limit(1)
    ).first()
    if kept is not None and kept.app_session is not None:
        if claude_desktop.still_matches(kept.app_session, session_id, folders):
            return claude_desktop.Lookup(claude_desktop.FOUND, kept.app_session)
        session.execute(
            delete(AgentSessionEvent).where(
                AgentSessionEvent.agent == "claude",
                AgentSessionEvent.session_id == session_id,
                AgentSessionEvent.source == APP,
            )
        )
        session.commit()
    key = _miss_key(session_id, folders)
    with _misses_lock:
        missed = _misses.get(key)
    if missed is not None and now < missed[1]:
        return claude_desktop.Lookup(missed[0])
    found = claude_desktop.find(session_id, folders, now)
    if found.state == claude_desktop.FOUND:
        with _misses_lock:
            _misses.pop(key, None)
        session.add(
            AgentSessionEvent(
                agent="claude",
                session_id=session_id,
                source=APP,
                app_session=found.record,
                created_at=now,
            )
        )
        session.commit()
    else:
        with _misses_lock:
            for old in [k for k, (_, until) in _misses.items() if until <= now]:
                del _misses[old]
            if len(_misses) >= _MISS_LIMIT:
                _misses.clear()
            _misses[key] = (found.state, now + MISS_FOR)
    return found


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
            # words, not what the session worked on: token use follows the records of the MCP
            # server and of the hooks, which saw the agent's own calls.
            AgentSessionEvent.source.in_((TASK, HOOK_TASK)),
            AgentSessionEvent.created_at.between(since, until),
        )
    ):
        found[(agent, session_id)].append((_aware(at), task_id))
    for items in found.values():
        items.sort()
    return found

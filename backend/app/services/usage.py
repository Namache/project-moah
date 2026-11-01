"""Token and time use by Claude Code and Codex, read from their own logs on this computer.

Only counts, times, model and tool names, folder paths and the size of tool output are kept.
Message and tool text is never stored or returned.
Logs are read incrementally: each call reads only the bytes appended since the last one, so the
dashboard can refresh every few seconds while the agents are working.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.services.tokens import base_tokens

AGENTS = ("claude", "codex")
RETENTION = timedelta(days=31)
ACTIVE_GAP = timedelta(minutes=5)
PORTAL_PREFIX = "/run/user/"
PORTAL_XATTR = "user.document-portal.host-path"


@dataclass(slots=True)
class UsageEvent:
    at: datetime
    agent: str
    session: str
    cwd: str
    model: str
    fresh_input: int
    cached: int
    output: int

    @property
    def fresh(self) -> int:
        return self.fresh_input + self.output


@dataclass(slots=True)
class ToolEvent:
    at: datetime
    agent: str
    session: str
    cwd: str
    tool: str
    output_chars: int = 0


@dataclass(slots=True)
class PackSample:
    """One context pack and the tokens it really added to the conversation.

    ``actual`` is how much the next request's prompt grew over the one that asked for the pack,
    less that reply's own output: the pack's tool result. Taken only when nothing else (another
    tool result, a reminder, a message) went in between."""

    at: datetime
    session: str
    model: str
    estimate_base: int  # services/tokens.base_tokens of the result, provider-neutral
    actual: int


@dataclass(slots=True)
class TaskMark:
    """A Project Moah tool result in an agent's log that named the session's task."""

    at: datetime
    agent: str
    session: str
    task: str  # human id, such as PROJ-017


@dataclass(slots=True)
class _Reply:
    id: str
    prompt: int
    output: int
    tools: int = 0


@dataclass(slots=True)
class _Pending:
    reply: str
    prompt: int
    output: int
    estimate_base: int


SUBAGENT_TOOLS = {"Agent", "Task", "spawn_agent"}
PACK_TOOL = "brain_context_pack"
# What Project Moah's MCP tools say about the session's task (server.py).
TASK_MARK = re.compile(
    r"This session's task is ([A-Z][A-Z0-9]*-\d+)"
    r"|\\?\"session_task\\?\":\s*\\?\"([A-Z][A-Z0-9]*-\d+)"
)


def moah_tool(name: str) -> str | None:
    """The Project Moah tool a call is for (brain_...), whatever the agent named the server."""
    last = re.split(r"__|\.|/", name)[-1]
    return last if last.startswith("brain_") else None


def _text(content: object) -> str:
    """The text of a tool result, only ever used here to count it or find a task id."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            _text(item.get("text") if isinstance(item, dict) else item) for item in content
        )
    if isinstance(content, dict):
        return _text(content.get("output") or content.get("text") or content.get("content"))
    return ""


def task_marks_in(text: str) -> list[str]:
    return [a or b for a, b in TASK_MARK.findall(text)]


def tool_label(name: str) -> str:
    """One name per tool: MCP tools are grouped by server, as `MCP: server`."""
    if name.startswith("mcp__"):
        parts = name.split("__")
        return f"MCP: {parts[1] if len(parts) > 1 else name}"
    return name or "unknown"


def _text_size(content: object) -> int:
    """Characters of text in a tool result, without keeping the text."""
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(
            _text_size(item.get("text") if isinstance(item, dict) else item) for item in content
        )
    if isinstance(content, dict):
        return _text_size(content.get("output") or content.get("text") or content.get("content"))
    return 0


@dataclass
class _FileState:
    identity: tuple[int, int]
    offset: int = 0
    cwd: str = ""
    model: str = ""
    events: dict[str, UsageEvent] = field(default_factory=dict)
    tools: dict[str, ToolEvent] = field(default_factory=dict)
    compactions: list[tuple[datetime, str, str]] = field(default_factory=list)
    moah_calls: dict[str, str] = field(default_factory=dict)  # tool call id -> brain_ tool
    marks: list[TaskMark] = field(default_factory=list)
    samples: list[PackSample] = field(default_factory=list)
    reply: _Reply | None = None
    pending: _Pending | None = None
    limits: dict | None = None
    limits_at: datetime | None = None


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _int(value: object) -> int:
    return value if isinstance(value, int) and value > 0 else 0


WINDOWS_FOLDER = re.compile(r"^[A-Za-z]:[\\/]")


def folder_key(path: str) -> str:
    """How folders compare: Windows ignores case (C:/Users/Me is c:/users/me), Linux does not."""
    return path.casefold() if WINDOWS_FOLDER.match(path) else path


def inside_folder(path: str, root: str) -> bool:
    """Whether a folder is root itself or anywhere below it."""
    path, root = folder_key(path), folder_key(root)
    return path == root or path.startswith(root.rstrip("/") + "/")


def normalize_folder(path: str) -> str:
    """One spelling per folder: /var/home is /home, a portal path names its host folder, and a
    Windows folder is written with forward slashes (C:/Users/me/game), so one comparison by "/"
    fits every system."""
    if WINDOWS_FOLDER.match(path):
        path = (path[0].upper() + path[1:].replace("\\", "/")).rstrip("/")
        return path if len(path) > 2 else path + "/"
    if path.startswith(PORTAL_PREFIX) and "/doc/" in path and hasattr(os, "getxattr"):
        try:
            path = os.getxattr(path, PORTAL_XATTR).decode()
        except OSError:
            pass
    path = path.rstrip("/") or "/"
    return path[4:] if path.startswith("/var/home/") else path


class UsageReader:
    """Keeps parsed usage per log file and re-reads only what was appended since the last call."""

    def __init__(self, claude_dir: Path | None = None, codex_dir: Path | None = None) -> None:
        self.claude_dir = claude_dir
        self.codex_dir = codex_dir
        self._files: dict[Path, _FileState] = {}
        self._lock = threading.Lock()

    def roots(self) -> dict[str, Path]:
        return {
            "claude": (self.claude_dir or claude_home()) / "projects",
            "codex": (self.codex_dir or codex_home()) / "sessions",
        }

    def refresh(self, now: datetime | None = None) -> tuple[list[UsageEvent], dict | None]:
        events, limits, _, _ = self.refresh_all(now)
        return events, limits

    def refresh_all(
        self, now: datetime | None = None
    ) -> tuple[list[UsageEvent], dict | None, list[ToolEvent], list[tuple[datetime, str, str]]]:
        """Usage, Codex limits, tool calls, and compactions as (time, agent, session)."""
        now = now or datetime.now(UTC)
        oldest = now - RETENTION
        with self._lock:
            seen: set[Path] = set()
            for agent, root in self.roots().items():
                if not root.is_dir():
                    continue
                for path in root.rglob("*.jsonl"):
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    if stat.st_mtime < oldest.timestamp():
                        continue
                    seen.add(path)
                    self._read(agent, path, stat)
            for gone in set(self._files) - seen:
                del self._files[gone]
            events = [
                event
                for state in self._files.values()
                for event in state.events.values()
                if event.at >= oldest
            ]
            latest = max(
                (s for s in self._files.values() if s.limits is not None),
                key=lambda s: s.limits_at or oldest,
                default=None,
            )
            tools = [
                tool
                for state in self._files.values()
                for tool in state.tools.values()
                if tool.at >= oldest
            ]
            compactions = [
                c for state in self._files.values() for c in state.compactions if c[0] >= oldest
            ]
            return events, latest.limits if latest else None, tools, compactions

    def task_marks(self) -> list[TaskMark]:
        """Task ids Project Moah's own tool results named, per log session (after a refresh)."""
        with self._lock:
            return [m for state in self._files.values() for m in state.marks]

    def pack_samples(self) -> list[PackSample]:
        """Context packs with the tokens they really cost in Claude Code (after a refresh)."""
        with self._lock:
            return [p for state in self._files.values() for p in state.samples]

    def _read(self, agent: str, path: Path, stat: os.stat_result) -> None:
        identity = (stat.st_dev, stat.st_ino)
        state = self._files.get(path)
        if state is None or state.identity != identity or stat.st_size < state.offset:
            state = self._files[path] = _FileState(identity=identity)
        if stat.st_size == state.offset:
            return
        try:
            with path.open("rb") as handle:
                handle.seek(state.offset)
                chunk = handle.read(stat.st_size - state.offset)
        except OSError:
            return
        end = chunk.rfind(b"\n")
        if end < 0:
            return  # a line is still being written; read it next time
        state.offset += end + 1
        session = path.stem
        for raw in chunk[: end + 1].splitlines():
            if agent == "claude" and any(
                marker in raw for marker in (b'"usage"', b'"tool_result"', b'"compact_boundary"')
            ):
                self._claude_line(state, session, raw)
            elif agent == "claude" and state.pending and _adds_context(raw):
                state.pending = None  # something besides the pack went in: no clean sample
            elif agent == "codex" and any(
                marker in raw
                for marker in (
                    b'"token_count"',
                    b'"session_meta"',
                    b'"turn_context"',
                    b'"response_item"',
                    b'"compacted"',
                )
            ):
                self._codex_line(state, session, raw)

    @staticmethod
    def _claude_line(state: _FileState, session: str, raw: bytes) -> None:
        try:
            record = json.loads(raw)
        except ValueError:
            return
        at = _timestamp(record.get("timestamp"))
        if at is None:
            return
        session_id = str(record.get("sessionId") or session)
        cwd = normalize_folder(str(record.get("cwd") or ""))
        main = not record.get("isSidechain")
        if record.get("subtype") == "compact_boundary":
            state.compactions.append((at, "claude", session_id))
            state.pending = None
            return
        message = record.get("message")
        if not isinstance(message, dict):
            return
        blocks = message.get("content") if isinstance(message.get("content"), list) else []
        uses = results = 0
        pack_result: str | None = None
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("id"):
                uses += 1
                name = str(block.get("name") or "")
                if block["id"] not in state.tools:
                    state.tools[block["id"]] = ToolEvent(
                        at, "claude", session_id, cwd, tool_label(name)
                    )
                if moah := moah_tool(name):
                    state.moah_calls[block["id"]] = moah
            elif block.get("type") == "tool_result":
                results += 1
                call = block.get("tool_use_id")
                if call in state.tools:
                    state.tools[call].output_chars = _text_size(block.get("content"))
                if call in state.moah_calls:
                    text = _text(block.get("content"))
                    for task in task_marks_in(text):
                        state.marks.append(TaskMark(at, "claude", session_id, task))
                    if state.moah_calls.pop(call) == PACK_TOOL:
                        pack_result = text
        if main and record.get("type") == "user":
            reply = state.reply
            state.pending = None
            if pack_result is not None and results == 1 and reply and reply.tools == 1:
                state.pending = _Pending(
                    reply.id, reply.prompt, reply.output, base_tokens(pack_result)
                )
        if not isinstance(message.get("usage"), dict):
            return
        usage = message["usage"]
        # One reply is written as several lines that repeat its usage; the last one is complete.
        key = str(message.get("id") or record.get("uuid") or len(state.events))
        prompt = (
            _int(usage.get("input_tokens"))
            + _int(usage.get("cache_creation_input_tokens"))
            + _int(usage.get("cache_read_input_tokens"))
        )
        if main:
            pending = state.pending
            if pending and pending.reply != key:
                grew = prompt - pending.prompt - pending.output
                if grew > 0 and pending.estimate_base > 0:
                    state.samples.append(
                        PackSample(
                            at,
                            session_id,
                            str(message.get("model") or ""),
                            pending.estimate_base,
                            grew,
                        )
                    )
            state.pending = None  # taken, or the same reply went on after the result
            if state.reply is None or state.reply.id != key:
                state.reply = _Reply(key, prompt, _int(usage.get("output_tokens")))
            state.reply.prompt = prompt
            state.reply.output = _int(usage.get("output_tokens"))
            state.reply.tools += uses
        state.events[key] = UsageEvent(
            at=at,
            agent="claude",
            session=session_id,
            cwd=cwd,
            model=str(message.get("model") or ""),
            fresh_input=_int(usage.get("input_tokens"))
            + _int(usage.get("cache_creation_input_tokens")),
            cached=_int(usage.get("cache_read_input_tokens")),
            output=_int(usage.get("output_tokens")),
        )

    @staticmethod
    def _codex_line(state: _FileState, session: str, raw: bytes) -> None:
        try:
            record = json.loads(raw)
        except ValueError:
            return
        payload = record.get("payload")
        if not isinstance(payload, dict):
            return
        kind = record.get("type")
        at = _timestamp(record.get("timestamp"))
        if kind == "compacted" or (kind == "response_item" and payload.get("type") == "compaction"):
            if at is not None:
                state.compactions.append((at, "codex", session))
            return
        if kind == "response_item":
            item = payload.get("type")
            call = str(payload.get("call_id") or payload.get("id") or "")
            if item in ("function_call", "custom_tool_call", "local_shell_call") and at and call:
                name = "exec" if item == "local_shell_call" else str(payload.get("name") or "")
                state.tools.setdefault(
                    call, ToolEvent(at, "codex", session, state.cwd, tool_label(name))
                )
                if moah := moah_tool(name):
                    state.moah_calls[call] = moah
            elif (
                item in ("function_call_output", "custom_tool_call_output") and call in state.tools
            ):
                state.tools[call].output_chars = _text_size(payload.get("output"))
                if call in state.moah_calls and at:
                    state.moah_calls.pop(call)
                    for task in task_marks_in(_text(payload.get("output"))):
                        state.marks.append(TaskMark(at, "codex", session, task))
            return
        if kind in ("session_meta", "turn_context"):
            if isinstance(payload.get("cwd"), str):
                state.cwd = normalize_folder(payload["cwd"])
            if isinstance(payload.get("model"), str):
                state.model = payload["model"]
            return
        if payload.get("type") != "token_count":
            return
        if at is None:
            return
        limits = payload.get("rate_limits")
        if isinstance(limits, dict):
            state.limits = {
                name: {
                    "used_percent": float(window.get("used_percent") or 0),
                    "window_minutes": _int(window.get("window_minutes")),
                    "resets_at": datetime.fromtimestamp(window["resets_at"], UTC).isoformat()
                    if isinstance(window.get("resets_at"), int | float)
                    else None,
                }
                for name, window in (
                    ("short", limits.get("primary")),
                    ("weekly", limits.get("secondary")),
                )
                if isinstance(window, dict)
            } | {"updated_at": at.isoformat()}
            state.limits_at = at
        info = payload.get("info")
        usage = info.get("last_token_usage") if isinstance(info, dict) else None
        if not isinstance(usage, dict):
            return
        cached = _int(usage.get("cached_input_tokens"))
        state.events[f"{at.isoformat()}#{len(state.events)}"] = UsageEvent(
            at=at,
            agent="codex",
            session=session,
            cwd=state.cwd,
            model=state.model,
            fresh_input=max(_int(usage.get("input_tokens")) - cached, 0),
            cached=cached,
            output=_int(usage.get("output_tokens")),
        )


CONTEXT_LINES = (b'"type":"attachment"', b'"type":"system"', b'"type":"user"')


def _adds_context(raw: bytes) -> bool:
    """Whether a Claude Code log line puts something into the next request (a reminder, a
    hook's output, a message), judged without parsing it. Subagent lines don't count."""
    compact = raw.replace(b'": "', b'":"')
    return any(m in compact for m in CONTEXT_LINES) and b'"isSidechain":true' not in compact


def active_seconds(times: list[datetime]) -> float:
    """Time with agent activity. A gap longer than five minutes counts as five minutes at most."""
    ordered = sorted(times)
    return sum(
        min(b - a, ACTIVE_GAP).total_seconds() for a, b in zip(ordered, ordered[1:], strict=False)
    )


def _home_group(folder: str) -> str:
    """A readable name for a folder no project claims: the first two levels below home."""
    home = normalize_folder(str(Path.home()))
    if inside_folder(folder, home) and len(folder) > len(home):
        parts = folder[len(home) + 1 :].split("/")
        return "~/" + "/".join(parts[:2])
    if folder.startswith(("/tmp/", "/var/tmp/")) or folder in ("/tmp", "/var/tmp"):
        return "Temporary folders"
    return folder or "Unknown folder"


def _totals(events: list[UsageEvent]) -> dict:
    return {
        "fresh_tokens": sum(e.fresh for e in events),
        "cached_tokens": sum(e.cached for e in events),
        "output_tokens": sum(e.output for e in events),
        "active_seconds": round(active_seconds([e.at for e in events])),
        "sessions": len({(e.agent, e.session) for e in events}),
    }


# A usage reply counts toward the task the agent last worked on in that project (a context pack
# for it, or a change it made to the task, a checkpoint or a record linked to it), within this
# long. Matches the MCP server's session task, which is forgotten after two idle hours.
TASK_GAP = timedelta(hours=2)
COMPLETED = "completed"


def _aware(at: datetime) -> datetime:
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def _by_session_id(
    items: list[UsageEvent], found: list[tuple[datetime, str]]
) -> list[tuple[UsageEvent, str | None]]:
    """Each reply of one log session with its task, from that session's own task changes.

    Like the MCP server's session task: a task holds until the next one, and is forgotten after
    two idle hours. Replies before the first task in a stretch of work go to that task, so the
    turn that fetched the pack is counted with it."""
    out: list[tuple[UsageEvent, str | None]] = []
    stretch: list[UsageEvent] = []
    opened = None  # when the stretch could first have set a task: after the previous one ended

    def close() -> None:
        inside = [s for s in found if (opened is None or s[0] > opened) and s[0] <= stretch[-1].at]
        for event in stretch:
            before = [s for s in inside if s[0] <= event.at]
            task = before[-1][1] if before else (inside[0][1] if inside else None)
            out.append((event, task))

    for event in items:
        if stretch and event.at - stretch[-1].at > TASK_GAP:
            close()
            opened = stretch[-1].at
            stretch = []
        stretch.append(event)
    if stretch:
        close()
    return out


def task_usage(
    session: Session,
    events: list[UsageEvent],
    project_of: dict[tuple[str, str], str],
    marks: list[TaskMark] | None = None,
) -> dict:
    """Real token use per task, from the agents' own logs: tokens per completed task.

    Matched by the log's session id first: the tasks Project Moah recorded for that session
    (services/agent_sessions.py, from Claude Code's session id) and the task ids Project Moah's
    own tool results in that log named (``marks``). A session with neither falls back to time:
    the latest task the agent fetched a context pack for or changed in the reply's project, at
    most ``TASK_GAP`` earlier. Replies with no task either way stay unassigned and are
    reported as such. ``project_of`` maps (agent, session) to the project id it worked in."""
    from app.models.checkpoint import ActivityEvent
    from app.models.graph import RetrievalSession
    from app.models.task import Task
    from app.services.agent_sessions import session_tasks

    empty_match = {"session": 0, "time": 0, "none": 0}
    if not events:
        return {
            "tasks": [],
            "completed_tasks": 0,
            "unassigned_fresh_tokens": 0,
            "matched_fresh_tokens": empty_match,
            "unassigned_share": None,
        }
    start = min(e.at for e in events) - TASK_GAP
    end = max(e.at for e in events)
    exact = session_tasks(session, start - RETENTION, end + TASK_GAP)
    if marks:
        names = {m.task for m in marks}
        by_name: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for task_id, project_id, human_id in session.execute(
            select(Task.id, Task.project_id, Task.human_id).where(Task.human_id.in_(names))
        ):
            by_name[human_id].append((task_id, project_id))
        for mark in marks:
            choices = by_name.get(mark.task, [])
            own = [t for t, p in choices if p == project_of.get((mark.agent, mark.session))]
            if own or len(choices) == 1:
                exact.setdefault((mark.agent, mark.session), []).append(
                    (mark.at, own[0] if own else choices[0][0])
                )
        for found in exact.values():
            found.sort()
    projects = set(project_of.values())
    signals: dict[tuple[str, str], list[tuple[datetime, str]]] = defaultdict(list)
    for project_id, agent, task_id, at in session.execute(
        select(
            RetrievalSession.project_id,
            RetrievalSession.agent,
            RetrievalSession.task_id,
            RetrievalSession.created_at,
        ).where(
            RetrievalSession.project_id.in_(projects),
            RetrievalSession.task_id.is_not(None),
            RetrievalSession.created_at.between(start, end),
        )
    ):
        if agent in AGENTS:
            signals[(project_id, agent)].append((_aware(at), task_id))
    for project_id, agent, task_id, at in session.execute(
        select(
            ActivityEvent.project_id,
            ActivityEvent.actor_type,
            ActivityEvent.task_id,
            ActivityEvent.timestamp,
        ).where(
            ActivityEvent.project_id.in_(projects),
            ActivityEvent.task_id.is_not(None),
            ActivityEvent.actor_type.in_(AGENTS),
            ActivityEvent.timestamp.between(start, end),
        )
    ):
        signals[(project_id, agent)].append((_aware(at), task_id))
    for found in signals.values():
        found.sort()

    per_task: dict[str, list[UsageEvent]] = defaultdict(list)
    matched = dict(empty_match)
    how: dict[int, str] = {}  # reply -> how it was matched
    by_session: dict[tuple[str, str], list[UsageEvent]] = defaultdict(list)
    for event in events:
        by_session[(event.agent, event.session)].append(event)
    for key, items in by_session.items():
        items.sort(key=lambda e: e.at)
        if key in exact:
            for event, task_id in _by_session_id(items, exact[key]):
                if task_id:
                    per_task[task_id].append(event)
                    how[id(event)] = "session"
                else:
                    matched["none"] += event.fresh
            continue
        project_id = project_of.get(key)
        found = signals.get((project_id, key[0]), []) if project_id else []
        inside = [s for s in found if items[0].at - TASK_GAP <= s[0] <= items[-1].at]
        for event in items:
            before = [s for s in inside if s[0] <= event.at and event.at - s[0] <= TASK_GAP]
            if before:
                per_task[before[-1][1]].append(event)
                how[id(event)] = "time"
            elif inside and inside[0][0] > event.at:
                per_task[inside[0][1]].append(event)  # the turn that led to the first signal
                how[id(event)] = "time"
            else:
                matched["none"] += event.fresh

    rows = []
    if per_task:
        tasks = {t.id: t for t in session.scalars(select(Task).where(Task.id.in_(per_task.keys())))}
        for task_id, items in per_task.items():
            task = tasks.get(task_id)
            for event in items:
                matched[how[id(event)] if task else "none"] += event.fresh
            if task is None:  # deleted since
                continue
            rows.append(
                {
                    "task_id": task.id,
                    "task": task.human_id,
                    "title": task.title,
                    "project_id": task.project_id,
                    "status": task.status,
                    **_totals(items),
                    "replies": len(items),
                }
            )
    rows.sort(key=lambda row: row["fresh_tokens"], reverse=True)
    done = [r for r in rows if r["status"] == COMPLETED]
    return {
        "tasks": rows,
        "completed_tasks": len(done),
        # Tokens the agent sent and received fresh (not read back from its cache), and all of
        # them including cache reads, per task that a person marked complete.
        "fresh_tokens_per_completed_task": (
            round(sum(r["fresh_tokens"] for r in done) / len(done)) if done else None
        ),
        "total_tokens_per_completed_task": (
            round(sum(r["fresh_tokens"] + r["cached_tokens"] for r in done) / len(done))
            if done
            else None
        ),
        "unassigned_fresh_tokens": matched["none"],
        # How replies were matched, in fresh tokens: by the log's session id, by time (sessions
        # Project Moah has no session record for), or not at all.
        "matched_fresh_tokens": matched,
        "unassigned_share": round(matched["none"] / total, 3)
        if (total := sum(matched.values()))
        else None,
    }


def _bucket_start(at: datetime, offset: timedelta, hourly: bool) -> datetime:
    """The start of the person's local hour or day containing `at`, as a UTC time."""
    local = at + offset
    local = local.replace(minute=0, second=0, microsecond=0)
    if not hourly:
        local = local.replace(hour=0)
    return local - offset


def usage_summary(
    session: Session,
    reader: UsageReader,
    since: datetime,
    now: datetime | None = None,
    *,
    until: datetime | None = None,
    agent: str | None = None,
    tz_offset_minutes: int = 0,
    bucket: str = "day",
) -> dict:
    """Usage between since and until (default now), for one agent or both, in local buckets.

    tz_offset_minutes is minutes east of UTC, so days match the person's clock.
    """
    now = now or datetime.now(UTC)
    since = max(since, now - RETENTION)
    end = min(until or now, now)
    events, limits, tools, compactions = reader.refresh_all(now)
    agents = (agent,) if agent in AGENTS else AGENTS
    events = [e for e in events if since <= e.at <= end and e.agent in agents]
    tools = [t for t in tools if since <= t.at <= end and t.agent in agents]
    compactions = [c for c in compactions if since <= c[0] <= end and c[1] in agents]

    projects = [
        (project, normalize_folder(project.root_path))
        for project in session.scalars(select(Project).where(Project.root_path.is_not(None)))
    ]
    # Deepest folder wins, as in the MCP server's project detection.
    projects.sort(key=lambda item: len(item[1]), reverse=True)

    def owner(folder: str) -> Project | None:
        for project, root in projects:
            if inside_folder(folder, root):
                return project
        return None

    def place(folder: str) -> tuple[str, str | None, str]:
        project = owner(folder) if folder else None
        if project:
            return project.id, project.id, project.name
        return "folder:" + _home_group(folder), None, _home_group(folder)

    by_project: dict[str, list[UsageEvent]] = defaultdict(list)
    names: dict[str, tuple[str | None, str]] = {}
    for event in events:
        key, pid, name = place(event.cwd)
        names[key] = (pid, name)
        by_project[key].append(event)

    hourly: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(AGENTS, 0))
    for event in events:
        hour = event.at.replace(minute=0, second=0, microsecond=0).isoformat()
        hourly[hour][event.agent] += event.fresh

    # The chart's buckets, on the person's clock: tokens, active time and sessions per agent.
    offset = timedelta(minutes=max(-14 * 60, min(14 * 60, tz_offset_minutes)))
    by_hour = bucket == "hour"
    step = timedelta(hours=1) if by_hour else timedelta(days=1)
    buckets: dict[datetime, list[UsageEvent]] = defaultdict(list)
    for event in events:
        buckets[_bucket_start(event.at, offset, by_hour)].append(event)
    series = []
    cursor = _bucket_start(since, offset, by_hour)
    while cursor <= end and len(series) < 800:
        items = buckets.get(cursor, [])
        series.append(
            {
                "start": cursor.isoformat(),
                **{
                    a: {
                        "fresh_tokens": sum(e.fresh for e in items if e.agent == a),
                        "active_seconds": round(
                            active_seconds([e.at for e in items if e.agent == a])
                        ),
                        "sessions": len({e.session for e in items if e.agent == a}),
                    }
                    for a in AGENTS
                },
            }
        )
        cursor += step

    models: dict[tuple[str, str], list[UsageEvent]] = defaultdict(list)
    for event in events:
        models[(event.agent, event.model or "unknown")].append(event)
    by_model = sorted(
        (
            {
                "agent": a,
                "model": m,
                "fresh_tokens": sum(e.fresh for e in items),
                "cached_tokens": sum(e.cached for e in items),
                "replies": len(items),
            }
            for (a, m), items in models.items()
        ),
        key=lambda row: row["fresh_tokens"],
        reverse=True,
    )

    tool_rows: dict[tuple[str, str], list[ToolEvent]] = defaultdict(list)
    for tool in tools:
        tool_rows[(tool.agent, tool.tool)].append(tool)
    by_tool = sorted(
        (
            {
                "agent": a,
                "tool": name,
                "calls": len(items),
                "output_chars": sum(t.output_chars for t in items),
            }
            for (a, name), items in tool_rows.items()
        ),
        key=lambda row: (row["output_chars"], row["calls"]),
        reverse=True,
    )

    per_session: dict[tuple[str, str], list[UsageEvent]] = defaultdict(list)
    for event in events:
        per_session[(event.agent, event.session)].append(event)
    compacted: dict[tuple[str, str], int] = defaultdict(int)
    for _, a, sid in compactions:
        compacted[(a, sid)] += 1
    session_rows = []
    for (a, sid), items in per_session.items():
        latest = max(items, key=lambda e: e.at)
        session_rows.append(
            {
                "agent": a,
                "session": sid[:12],
                "project": place(latest.cwd)[2],
                "project_id": place(latest.cwd)[1],
                "fresh_tokens": sum(e.fresh for e in items),
                "active_seconds": round(active_seconds([e.at for e in items])),
                "replies": len(items),
                "compactions": compacted.get((a, sid), 0),
                "models": sorted({e.model for e in items if e.model}),
                "last_at": latest.at.isoformat(),
            }
        )
    session_rows.sort(key=lambda row: row["fresh_tokens"], reverse=True)
    longest = max((row["active_seconds"] for row in session_rows), default=0)

    claude_replies = [e for e in events if e.agent == "claude"]
    signals = {
        "opus_reply_share": (
            sum("opus" in e.model for e in claude_replies) / len(claude_replies)
            if claude_replies
            else 0.0
        ),
        "compactions": {a: sum(1 for c in compactions if c[1] == a) for a in AGENTS},
        "subagents_started": {
            a: sum(1 for t in tools if t.agent == a and t.tool in SUBAGENT_TOOLS) for a in AGENTS
        },
        "tool_calls": {a: sum(1 for t in tools if t.agent == a) for a in AGENTS},
        "tool_output_chars": {
            a: sum(t.output_chars for t in tools if t.agent == a) for a in AGENTS
        },
    }

    rows = [
        {"project_id": names[key][0], "name": names[key][1], **_totals(items)}
        for key, items in by_project.items()
    ]
    project_of = {
        key: pid
        for key, items in per_session.items()
        if (pid := place(max(items, key=lambda e: e.at).cwd)[1])
    }
    by_task = task_usage(session, events, project_of, reader.task_marks())
    from app.services import token_calibration

    token_estimates = token_calibration.measure(reader.pack_samples())
    token_calibration.save(session, token_estimates)
    rows.sort(key=lambda row: row["fresh_tokens"], reverse=True)
    roots = reader.roots()
    return {
        "generated_at": now.isoformat(),
        "since": since.isoformat(),
        "until": end.isoformat(),
        "agent": agent if agent in AGENTS else None,
        "bucket": "hour" if by_hour else "day",
        "sources": {name: {"found": path.is_dir()} for name, path in roots.items()},
        "totals": _totals(events),
        "by_agent": {a: _totals([e for e in events if e.agent == a]) for a in AGENTS},
        "hourly": [{"hour": hour, **values} for hour, values in sorted(hourly.items())],
        "series": series,
        "projects": [row for row in rows if row["project_id"]],
        "other_folders": [row for row in rows if not row["project_id"]][:6],
        "by_model": by_model,
        "by_tool": by_tool[:30],
        "sessions": session_rows[:15],
        "by_task": {**by_task, "tasks": by_task["tasks"][:30]},
        "token_estimates": token_estimates,
        "signals": signals,
        "longest_session_seconds": round(longest),
        "codex_limits": limits,
    }

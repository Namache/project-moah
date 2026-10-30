"""Token and time use by Claude Code and Codex, read from their own logs on this computer.

Only counts, times, model and tool names, folder paths and the size of tool output are kept.
Message and tool text is never stored or returned.
Logs are read incrementally: each call reads only the bytes appended since the last one, so the
dashboard can refresh every few seconds while the agents are working.
"""

from __future__ import annotations

import json
import os
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project

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


SUBAGENT_TOOLS = {"Agent", "Task", "spawn_agent"}


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


def normalize_folder(path: str) -> str:
    """One spelling per folder: /var/home is /home, and a portal path names its host folder."""
    if path.startswith(PORTAL_PREFIX) and "/doc/" in path:
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
        if record.get("subtype") == "compact_boundary":
            state.compactions.append((at, "claude", session_id))
            return
        message = record.get("message")
        if not isinstance(message, dict):
            return
        for block in message.get("content") if isinstance(message.get("content"), list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("id"):
                if block["id"] not in state.tools:
                    state.tools[block["id"]] = ToolEvent(
                        at, "claude", session_id, cwd, tool_label(str(block.get("name") or ""))
                    )
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in state.tools:
                state.tools[block["tool_use_id"]].output_chars = _text_size(block.get("content"))
        if not isinstance(message.get("usage"), dict):
            return
        usage = message["usage"]
        # One reply is written as several lines that repeat its usage; the last one is complete.
        key = str(message.get("id") or record.get("uuid") or len(state.events))
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
            elif (
                item in ("function_call_output", "custom_tool_call_output") and call in state.tools
            ):
                state.tools[call].output_chars = _text_size(payload.get("output"))
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


def active_seconds(times: list[datetime]) -> float:
    """Time with agent activity. A gap longer than five minutes counts as five minutes at most."""
    ordered = sorted(times)
    return sum(
        min(b - a, ACTIVE_GAP).total_seconds() for a, b in zip(ordered, ordered[1:], strict=False)
    )


def _home_group(folder: str) -> str:
    """A readable name for a folder no project claims: the first two levels below home."""
    home = normalize_folder(str(Path.home()))
    if folder.startswith(home + "/"):
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
            if folder == root or folder.startswith(root + "/"):
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
        "signals": signals,
        "longest_session_seconds": round(longest),
        "codex_limits": limits,
    }

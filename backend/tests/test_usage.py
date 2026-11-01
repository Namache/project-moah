import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.mcp.projects import _inside
from app.services.usage import active_seconds, normalize_folder

pytestmark = pytest.mark.anyio

NOW = datetime.now(UTC).replace(microsecond=0)


def iso(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


def claude_line(
    message_id: str, minutes_ago: float, cwd: str, *, fresh=10, cache_write=0, cached=100, out=5
) -> dict:
    return {
        "type": "assistant",
        "timestamp": iso(minutes_ago),
        "cwd": cwd,
        "sessionId": "s1",
        "message": {
            "id": message_id,
            "model": "claude-test",
            "content": [{"type": "text", "text": "SECRET MESSAGE TEXT"}],
            "usage": {
                "input_tokens": fresh,
                "cache_creation_input_tokens": cache_write,
                "cache_read_input_tokens": cached,
                "output_tokens": out,
            },
        },
    }


def codex_lines(cwd: str, minutes_ago: float, *, used=40.0) -> list[dict]:
    resets = int((NOW + timedelta(hours=2)).timestamp())
    return [
        {
            "type": "session_meta",
            "timestamp": iso(minutes_ago + 1),
            "payload": {"cwd": cwd, "instructions": "SECRET"},
        },
        {
            "type": "event_msg",
            "timestamp": iso(minutes_ago),
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 1000,
                        "cached_input_tokens": 900,
                        "output_tokens": 50,
                    }
                },
                "rate_limits": {
                    "primary": {"used_percent": used, "window_minutes": 300, "resets_at": resets},
                    "secondary": {
                        "used_percent": 7.0,
                        "window_minutes": 10080,
                        "resets_at": resets,
                    },
                },
            },
        },
    ]


def write(path: Path, records: list[dict], mode: str = "w") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode) as handle:
        handle.writelines(json.dumps(record) + "\n" for record in records)


@pytest.fixture
def logs(tmp_path: Path, monkeypatch) -> dict[str, Path]:
    claude, codex = tmp_path / "claude", tmp_path / "codex"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    monkeypatch.setenv("CODEX_HOME", str(codex))
    return {
        "claude": claude / "projects" / "-home-me-game" / "s1.jsonl",
        "codex": codex / "sessions" / "2026" / "10" / "11" / "rollout-a.jsonl",
    }


@pytest.mark.skipif(sys.platform == "win32", reason="Linux folder layout (/home, /var/home)")
async def test_counts_both_agents_by_project_and_never_returns_text(
    client: AsyncClient, logs
) -> None:
    game = (
        await client.post("/api/projects", json={"name": "Game", "root_path": "/home/me/game"})
    ).json()
    await client.post("/api/projects", json={"name": "Engine", "root_path": "/home/me/game/engine"})
    write(
        logs["claude"],
        [
            # One reply written as two lines repeating its usage counts once.
            claude_line("m1", 30, "/home/me/game", out=2),
            claude_line("m1", 30, "/home/me/game", out=5),
            claude_line("m2", 20, "/var/home/me/game/src", cache_write=40),
            claude_line("m3", 10, "/home/me/game/engine"),
        ],
    )
    write(logs["codex"], codex_lines("/home/me/elsewhere/tool", 15))

    report = (await client.get("/api/usage")).json()
    assert "SECRET" not in json.dumps(report)
    assert report["by_agent"]["claude"]["fresh_tokens"] == (10 + 5) + (50 + 5) + (10 + 5)
    assert report["by_agent"]["claude"]["cached_tokens"] == 300
    assert report["by_agent"]["codex"]["fresh_tokens"] == 100 + 50
    assert report["by_agent"]["codex"]["cached_tokens"] == 900
    rows = {row["name"]: row for row in report["projects"]}
    # /var/home is the same folder as /home, and the deepest project folder wins.
    assert rows["Game"]["project_id"] == game["id"] and rows["Game"]["fresh_tokens"] == 15 + 55
    assert rows["Engine"]["fresh_tokens"] == 15
    assert [row["name"] for row in report["other_folders"]] == ["/home/me/elsewhere/tool"]
    assert report["codex_limits"]["short"]["used_percent"] == 40.0
    assert report["codex_limits"]["weekly"]["window_minutes"] == 10080
    assert report["sources"] == {"claude": {"found": True}, "codex": {"found": True}}
    assert (
        sum(hour["claude"] + hour["codex"] for hour in report["hourly"])
        == report["totals"]["fresh_tokens"]
    )


async def test_reads_only_what_was_appended_and_waits_for_whole_lines(
    client: AsyncClient, logs
) -> None:
    write(logs["claude"], [claude_line("m1", 30, "/x")])
    assert (await client.get("/api/usage")).json()["totals"]["fresh_tokens"] == 15

    write(logs["claude"], [claude_line("m2", 5, "/x")], mode="a")
    with logs["claude"].open("a") as handle:
        handle.write(json.dumps(claude_line("m3", 1, "/x"))[:40])  # still being written
    assert (await client.get("/api/usage")).json()["totals"]["fresh_tokens"] == 30

    with logs["claude"].open("a") as handle:
        handle.write(json.dumps(claude_line("m3", 1, "/x"))[40:] + "\n")
    assert (await client.get("/api/usage")).json()["totals"]["fresh_tokens"] == 45

    # A file that was replaced or shortened is read again from the start.
    write(logs["claude"], [claude_line("only", 2, "/x", fresh=1, out=1)])
    assert (await client.get("/api/usage")).json()["totals"]["fresh_tokens"] == 2


async def test_range_and_missing_logs(client: AsyncClient, logs) -> None:
    empty = (await client.get("/api/usage")).json()
    assert empty["sources"] == {"claude": {"found": False}, "codex": {"found": False}}
    assert empty["totals"]["fresh_tokens"] == 0 and empty["codex_limits"] is None

    write(logs["claude"], [claude_line("old", 60 * 24 * 10, "/x"), claude_line("new", 5, "/x")])
    since = (NOW - timedelta(hours=1)).isoformat()
    assert (await client.get("/api/usage", params={"since": since})).json()["totals"][
        "fresh_tokens"
    ] == 15
    assert (await client.get("/api/usage")).json()["totals"][
        "fresh_tokens"
    ] == 15  # default: 7 days
    naive = (await client.get("/api/usage", params={"since": "2026-10-01T00:00:00"})).status_code
    assert naive == 422


def test_active_time_caps_long_gaps() -> None:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    times = [
        start,
        start + timedelta(minutes=2),
        start + timedelta(hours=3),
        start + timedelta(hours=3, minutes=1),
    ]
    assert active_seconds(times) == (2 + 5 + 1) * 60
    assert active_seconds([]) == 0


def test_folder_spellings() -> None:
    assert normalize_folder("/var/home/me/game/") == "/home/me/game"
    # Windows folders get forward slashes and a capital drive letter, so one comparison fits all.
    assert normalize_folder("c:\\Users\\me\\game\\") == "C:/Users/me/game"
    assert normalize_folder("C:/Users/me/game") == "C:/Users/me/game"
    assert normalize_folder("C:\\") == "C:/"
    assert _inside(
        normalize_folder("C:\\Users\\me\\game\\src"), normalize_folder("C:\\Users\\me\\game")
    )
    assert not _inside(
        normalize_folder("C:\\Users\\me\\gamer"), normalize_folder("C:\\Users\\me\\game")
    )
    assert normalize_folder("/home/me/game") == "/home/me/game"
    assert normalize_folder("/run/user/1000/doc/missing/game") == "/run/user/1000/doc/missing/game"


def claude_tool_lines(minutes_ago: float, cwd: str) -> list[dict]:
    return [
        {
            "type": "assistant",
            "timestamp": iso(minutes_ago),
            "cwd": cwd,
            "sessionId": "s9",
            "message": {
                "id": "t1",
                "model": "claude-opus-test",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call-1",
                        "name": "Bash",
                        "input": {"command": "SECRET CMD"},
                    },
                    {"type": "tool_use", "id": "call-2", "name": "mcp__project-brain__brain_brief"},
                    {"type": "tool_use", "id": "call-3", "name": "Agent"},
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        },
        {
            "type": "user",
            "timestamp": iso(minutes_ago - 0.5),
            "cwd": cwd,
            "sessionId": "s9",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call-1",
                        "content": "SECRET OUTPUT 1234",
                    },
                    {
                        "type": "tool_result",
                        "tool_use_id": "call-2",
                        "content": [{"type": "text", "text": "abc"}],
                    },
                ]
            },
        },
        {
            "type": "system",
            "subtype": "compact_boundary",
            "timestamp": iso(minutes_ago - 1),
            "sessionId": "s9",
        },
    ]


def codex_tool_lines(minutes_ago: float) -> list[dict]:
    return [
        {
            "type": "turn_context",
            "timestamp": iso(minutes_ago + 1),
            "payload": {"cwd": "/x", "model": "gpt-test"},
        },
        {
            "type": "response_item",
            "timestamp": iso(minutes_ago),
            "payload": {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "c1",
                "input": "SECRET",
            },
        },
        {
            "type": "response_item",
            "timestamp": iso(minutes_ago),
            "payload": {"type": "custom_tool_call_output", "call_id": "c1", "output": "12345678"},
        },
        {
            "type": "response_item",
            "timestamp": iso(minutes_ago),
            "payload": {"type": "function_call", "name": "spawn_agent", "call_id": "c2"},
        },
        {"type": "response_item", "timestamp": iso(minutes_ago), "payload": {"type": "compaction"}},
    ]


async def test_breakdowns_by_model_tool_and_session_without_text(client: AsyncClient, logs) -> None:
    write(logs["claude"], claude_tool_lines(30, "/x"))
    write(logs["codex"], codex_tool_lines(20) + codex_lines("/x", 10))
    report = (await client.get("/api/usage")).json()
    assert "SECRET" not in json.dumps(report)
    tools = {(t["agent"], t["tool"]): t for t in report["by_tool"]}
    assert tools[("claude", "Bash")] == {
        "agent": "claude",
        "tool": "Bash",
        "calls": 1,
        "output_chars": 18,
    }
    assert tools[("claude", "MCP: project-brain")]["output_chars"] == 3
    assert tools[("codex", "exec")]["output_chars"] == 8
    signals = report["signals"]
    assert signals["subagents_started"] == {"claude": 1, "codex": 1}
    assert signals["compactions"] == {"claude": 1, "codex": 1}
    assert signals["opus_reply_share"] == 1.0
    assert {(m["agent"], m["model"]) for m in report["by_model"]} == {
        ("claude", "claude-opus-test"),
        ("codex", "gpt-test"),
    }
    claude_session = next(s for s in report["sessions"] if s["agent"] == "claude")
    assert claude_session["compactions"] == 1 and claude_session["models"] == ["claude-opus-test"]


async def test_agent_filter_until_and_local_days(client: AsyncClient, logs) -> None:
    write(logs["claude"], [claude_line("a", 60 * 30, "/x"), claude_line("b", 5, "/x")])
    write(logs["codex"], codex_lines("/x", 10))
    only_codex = (await client.get("/api/usage", params={"agent": "codex"})).json()
    assert (
        only_codex["totals"]["fresh_tokens"] == 150
        and only_codex["by_agent"]["claude"]["fresh_tokens"] == 0
    )
    until = (NOW - timedelta(hours=2)).isoformat()
    early = (await client.get("/api/usage", params={"until": until})).json()
    assert early["totals"]["fresh_tokens"] == 15  # only the reply from 30 hours ago
    days = (await client.get("/api/usage", params={"tz_offset": 120})).json()
    assert days["bucket"] == "day" and 7 <= len(days["series"]) <= 9
    assert (
        sum(b["claude"]["fresh_tokens"] + b["codex"]["fresh_tokens"] for b in days["series"])
        == days["totals"]["fresh_tokens"]
    )
    hours = (
        await client.get(
            "/api/usage", params={"bucket": "hour", "since": (NOW - timedelta(hours=3)).isoformat()}
        )
    ).json()
    assert 3 <= len(hours["series"]) <= 5


@pytest.mark.skipif(sys.platform == "win32", reason="Linux folder layout (/home, /var/home)")
async def test_real_tokens_per_completed_task(client: AsyncClient, logs, database_url) -> None:
    from app.db.session import make_engine, make_session_factory
    from app.models.checkpoint import ActivityEvent
    from app.models.graph import RetrievalSession

    game = (
        await client.post("/api/projects", json={"name": "Game", "root_path": "/home/me/game"})
    ).json()
    base = f"/api/projects/{game['id']}/tasks"
    first = (await client.post(base, json={"title": "Fix old saves"})).json()
    second = (await client.post(base, json={"title": "Camp header"})).json()
    with make_session_factory(make_engine(database_url))() as session:
        # Claude fetched a pack for the first task, then changed the second one.
        session.add(
            RetrievalSession(
                project_id=game["id"],
                task_id=first["id"],
                operation="coding",
                agent="claude",
                items=[],
                created_at=NOW - timedelta(minutes=35),
            )
        )
        session.add(
            ActivityEvent(
                project_id=game["id"],
                task_id=second["id"],
                task_project_id=game["id"],
                event_type="TASK_UPDATED",
                actor_type="claude",
                timestamp=NOW - timedelta(minutes=25),
            )
        )
        session.commit()
    write(
        logs["claude"],
        [
            claude_line("m1", 40, "/home/me/game"),  # the turn that asked for the pack
            claude_line("m2", 30, "/home/me/game/src"),
            claude_line("m3", 20, "/home/me/game"),
        ],
    )
    await client.patch(f"{base}/{first['id']}", json={"status": "completed"})

    by_task = (await client.get("/api/usage")).json()["by_task"]
    rows = {row["task"]: row for row in by_task["tasks"]}
    assert rows[first["human_id"]]["fresh_tokens"] == 2 * 15
    assert rows[first["human_id"]]["replies"] == 2
    assert rows[second["human_id"]]["fresh_tokens"] == 15
    assert by_task["completed_tasks"] == 1
    assert by_task["fresh_tokens_per_completed_task"] == 30
    assert by_task["total_tokens_per_completed_task"] == 30 + 200
    assert by_task["unassigned_fresh_tokens"] == 0

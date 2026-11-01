"""Token use matched to tasks by the agent's session id (PROJ-017), and Claude's token factor
measured from the token jump each context pack causes in Claude Code's log (PROJ-018)."""

import io
import json
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.db.session import make_engine, make_session_factory
from app.models.agent_session import AgentSessionEvent
from app.services import tokens
from app.services.agent_sessions import SessionTracker, read_hook_input, record_start
from app.services.token_calibration import load, measure, save
from app.services.usage import PackSample, UsageReader, moah_tool, task_marks_in
from tests.test_usage import claude_line, iso, logs, write  # noqa: F401 - logs is a fixture

pytestmark = pytest.mark.anyio

NOW = datetime.now(UTC).replace(microsecond=0)
PACK = (
    "PROJECT\nGame\n\nCURRENT TASK\nGAME-1 — Fix old saves\n\n"
    + "WARNINGS\nNever write saves while autosave runs\n" * 12
)


@pytest.fixture(autouse=True)
def fixed_factor():
    tokens.use_measured("claude", None)
    yield
    tokens.use_measured("claude", None)


def factory(database_url: str):
    return make_session_factory(make_engine(database_url))


# ---- the hook and the MCP server's session ------------------------------------------------


def test_hook_input_is_read_without_waiting_forever() -> None:
    payload = {"session_id": "abc-1", "source": "clear", "cwd": "/home/me/game"}
    assert read_hook_input(io.StringIO(json.dumps(payload))) == payload
    assert read_hook_input(io.StringIO("not json")) == {}

    class Silent(io.StringIO):
        def read(self, *_):  # standard input left open by whoever ran the command
            import time

            time.sleep(5)
            return ""

    assert read_hook_input(Silent(), timeout=0.05) == {}


async def test_mcp_server_follows_clear_and_records_each_sessions_task(
    client: AsyncClient, database_url: str
) -> None:
    game = (await client.post("/api/projects", json={"name": "Game"})).json()
    task = (await client.post(f"/api/projects/{game['id']}/tasks", json={"title": "A"})).json()
    env = {"CLAUDE_CODE_SESSION_ID": "first", "CLAUDE_PID": "4242"}
    with factory(database_url)() as session:
        record_start(
            session, "claude", {"session_id": "first", "source": "startup"}, game["id"], env
        )
        tracker = SessionTracker("claude", {"CLAUDE_CODE_SESSION_ID": "first"})
        assert tracker.refresh(session) is False and tracker.current == "first"
        tracker.record_tasks(session, {game["id"]: task["id"]})
        tracker.record_tasks(session, {game["id"]: task["id"]})  # unchanged: not stored again
        # /clear: same Claude Code process, new session id.
        record_start(
            session, "claude", {"session_id": "second", "source": "clear"}, game["id"], env
        )
        # Another Claude Code window in the same project must not be followed.
        record_start(session, "claude", {"session_id": "other"}, game["id"], {"CLAUDE_PID": "7"})
        assert tracker.refresh(session) is True and tracker.current == "second"
        tracker.record_tasks(session, {game["id"]: task["id"]})
        rows = session.query(AgentSessionEvent).order_by(AgentSessionEvent.id).all()
        assert [(r.session_id, r.source, r.task_id is not None) for r in rows] == [
            ("first", "startup", False),
            ("first", "task", True),
            ("second", "clear", False),
            ("other", "startup", False),
            ("second", "task", True),
        ]
        # No session id anywhere: nothing is recorded, nothing breaks.
        assert record_start(session, "claude", {}, None, {}) is None
        assert SessionTracker("codex", {}).refresh(session) is False


async def test_brief_hook_records_the_session(
    client: AsyncClient, monkeypatch, database_url: str
) -> None:
    from app.mcp import server

    monkeypatch.setenv("PROJECT_BRAIN_DATABASE_URL", database_url)
    monkeypatch.setattr(server, "get_database_url", lambda: database_url)
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(json.dumps({"session_id": "hook-1", "source": "startup"}))
    )
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/nowhere")
    assert server.main(["--brief"]) == 0
    with factory(database_url)() as session:
        row = session.query(AgentSessionEvent).one()
        assert (row.agent, row.session_id, row.source) == ("claude", "hook-1", "startup")


# ---- reading packs and task ids from the logs ----------------------------------------------


def test_moah_tools_and_task_marks() -> None:
    assert moah_tool("mcp__project-moah__brain_context_pack") == "brain_context_pack"
    assert moah_tool("mcp__project-brain__brain_create_memory") == "brain_create_memory"
    assert moah_tool("mcp__other__search") is None
    text = "retrieval R-1\nThis session's task is GAME-7: what you write now is linked to it."
    assert task_marks_in(text) == ["GAME-7"]
    assert task_marks_in(json.dumps({"id": "x", "session_task": "GAME-8"})) == ["GAME-8"]


def pack_turn(
    reply: str,
    minutes_ago: float,
    *,
    prompt: int,
    out: int,
    result: str = PACK,
    task: str = "GAME-1",
    extra_tool: bool = False,
) -> list[dict]:
    """A reply that calls brain_context_pack, and its tool result."""
    use = {
        "type": "tool_use",
        "id": f"t-{reply}",
        "name": "mcp__project-moah__brain_context_pack",
        "input": {"task": task},
    }
    lines = [
        claude_line(reply, minutes_ago, "/home/me/game", fresh=prompt, cached=0, out=out)
        | {"type": "assistant"}
    ]
    lines[0]["message"]["content"] = [use]
    if extra_tool:
        second = json.loads(json.dumps(lines[0]))
        second["message"]["content"] = [{"type": "tool_use", "id": f"u-{reply}", "name": "Bash"}]
        lines.append(second)
    body = f"{result}\n\nThis session's task is {task}: what you write now is linked to it."
    lines.insert(
        1,
        {
            "type": "user",
            "timestamp": iso(minutes_ago - 0.1),
            "sessionId": "s1",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": f"t-{reply}",
                        "content": [{"type": "text", "text": body}],
                    }
                ],
            },
        },
    )
    return lines


def next_reply(reply: str, minutes_ago: float, prompt: int) -> dict:
    return claude_line(reply, minutes_ago, "/home/me/game", fresh=prompt, cached=0, out=20)


def test_each_pack_is_measured_by_the_jump_it_causes(logs) -> None:  # noqa: F811
    from app.services.tokens import base_tokens

    body = f"{PACK}\n\nThis session's task is GAME-1: what you write now is linked to it."
    base = base_tokens(body)
    write(
        logs["claude"],
        [
            *pack_turn("a", 30, prompt=1000, out=50),
            next_reply("b", 29, 1000 + 50 + 2 * base),  # clean: the pack alone went in
            *pack_turn("c", 20, prompt=3000, out=40),
            {"type": "attachment", "timestamp": iso(19.5), "attachment": {"type": "reminder"}},
            next_reply("d", 19, 9000),  # a reminder went in too: no sample
            *pack_turn("e", 10, prompt=10000, out=30, extra_tool=True),
            next_reply("f", 9, 12000),  # two tools in one reply: no sample
        ],
    )
    reader = UsageReader()
    reader.refresh()
    samples = reader.pack_samples()
    assert [(s.estimate_base, s.actual, s.model) for s in samples] == [
        (base, 2 * base, "claude-test")
    ]
    assert [m.task for m in reader.task_marks()] == ["GAME-1", "GAME-1", "GAME-1"]


# ---- calibration ---------------------------------------------------------------------------


def sample(model: str, base: int, actual: int, minutes_ago: float = 1) -> PackSample:
    return PackSample(NOW - timedelta(minutes=minutes_ago), "s", model, base, actual)


async def test_factor_is_measured_per_model_and_used_for_counts(
    client: AsyncClient, database_url: str
) -> None:
    ratios = [1.85, 1.95, 1.9, 2.0, 1.88, 1.92]
    samples = [sample("new", 400, round(400 * r)) for r in ratios]
    samples += [sample("old", 300, 360, minutes_ago=600) for _ in range(6)]
    samples.append(sample("new", 10, 90))  # too small to say anything: left out
    result = measure(samples)
    new, old = result["models"]
    assert (new["model"], new["packs"], old["model"]) == ("new", 6, "old")
    assert 1.89 <= new["factor"] <= 1.93 and old["factor"] == 1.2
    assert new["error_fixed"] > 0.3  # 1.2 undercounts this model's packs by about 37%
    assert new["error_measured"] <= 0.10
    assert result["in_use"] == {"model": "new", "factor": new["factor"]}

    with factory(database_url)() as session:
        text = "Never write saves while autosave runs. " * 20
        before = tokens.count_tokens(text, "claude")
        save(session, result)
        assert tokens.count_tokens(text, "claude") > before * 1.5
        assert tokens.count_tokens(text, "codex") == tokens.base_tokens(text)
        tokens.use_measured("claude", None)
        assert load(session) == new["factor"]  # the MCP server picks it up from the database
        assert tokens.factor("claude") == new["factor"]


def test_too_few_packs_keep_the_fixed_factor() -> None:
    result = measure([sample("new", 400, 800) for _ in range(4)])
    assert result["in_use"] is None and result["models"][0]["packs"] == 4


# ---- matching by session id ------------------------------------------------------------------


async def test_usage_matches_tasks_by_session_id(
    client: AsyncClient,
    logs,  # noqa: F811
    database_url: str,
) -> None:
    game = (
        await client.post("/api/projects", json={"name": "Game", "root_path": "/home/me/game"})
    ).json()
    base = f"/api/projects/{game['id']}/tasks"
    first = (await client.post(base, json={"title": "Fix old saves"})).json()
    second = (await client.post(base, json={"title": "Camp header"})).json()
    with factory(database_url)() as session:
        # The MCP server recorded the second task for session s1, 25 minutes ago.
        session.add(
            AgentSessionEvent(
                agent="claude",
                session_id="s1",
                project_id=game["id"],
                task_id=second["id"],
                source="task",
                created_at=NOW - timedelta(minutes=25),
            )
        )
        session.commit()
    write(
        logs["claude"],
        [
            # The log itself names the first task (a pack 40 minutes ago)...
            *pack_turn("m1", 40, prompt=10, out=5, task=first["human_id"]),
            next_reply("m2", 30, 10),
            # ...then the session moved to the second task (recorded by the MCP server).
            next_reply("m3", 20, 10),
            next_reply("m4", 2, 10),
        ],
    )
    write(  # another session that never touched a task
        logs["claude"].with_name("s2.jsonl"),
        [claude_line("x1", 15, "/home/me/game", fresh=4, cached=0, out=1) | {"sessionId": "s2"}],
    )
    by_task = (await client.get("/api/usage")).json()["by_task"]
    rows = {row["task"]: row for row in by_task["tasks"]}
    assert rows[first["human_id"]]["replies"] == 2
    assert rows[second["human_id"]]["replies"] == 2
    matched = by_task["matched_fresh_tokens"]
    assert matched["session"] == 15 + 30 + 30 + 30 and matched["none"] == 5
    assert by_task["unassigned_share"] == round(5 / (matched["session"] + 5), 3)


def test_session_task_is_forgotten_after_two_idle_hours() -> None:
    from app.services.usage import UsageEvent, _by_session_id

    def reply(minutes_ago: float) -> UsageEvent:
        return UsageEvent(NOW - timedelta(minutes=minutes_ago), "claude", "s", "", "m", 1, 0, 1)

    items = [reply(300), reply(290), reply(100), reply(90)]
    found = [(NOW - timedelta(minutes=295), "A"), (NOW - timedelta(minutes=95), "B")]
    assert [t for _, t in _by_session_id(items, found)] == ["A", "A", "B", "B"]
    assert [t for _, t in _by_session_id(items, found[:1])] == ["A", "A", None, None]

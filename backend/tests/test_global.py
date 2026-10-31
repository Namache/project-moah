"""The Global scope (rules for every project), links between memories, and the session brief."""

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from mcp.client.stdio import get_default_environment

from app.core.resources import resource_path
from tests.conftest import app_client
from tests.test_mcp import BACKEND, agent, call

pytestmark = pytest.mark.anyio


async def rule(client: AsyncClient, project: str, title: str, **extra) -> dict:
    response = await client.post(
        f"/api/projects/{project}/memory", json={"type": "rule", "title": title, **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_global_scope_is_reserved_and_hidden_from_project_lists(client: AsyncClient) -> None:
    await client.post("/api/projects", json={"name": "Trailhead"})
    assert [p["name"] for p in (await client.get("/api/projects")).json()] == ["Trailhead"]
    scope = (await client.get("/api/projects/global")).json()
    assert scope["name"] == "Global"
    assert (await client.patch("/api/projects/global", json={"name": "Mine"})).status_code == 409
    assert (await client.post("/api/projects/global/archive")).status_code == 409
    ok = await client.patch("/api/projects/global", json={"description": "Rules for everything"})
    assert ok.status_code == 200


async def test_global_rules_are_essential_in_every_context_pack(client: AsyncClient) -> None:
    pid = (await client.post("/api/projects", json={"name": "Trailhead"})).json()["id"]
    await rule(client, "global", "Ask before building", content="Wait for a clear yes.")
    await rule(client, "global", "Hidden one", ai_visibility="hidden")
    await client.post(
        "/api/projects/global/memory",
        json={"type": "fact", "title": "Prefers short answers", "ai_visibility": "always"},
    )
    pack = (
        await client.get(
            f"/api/projects/{pid}/context", params={"detail": "minimal", "budget": 100}
        )
    ).json()
    assert "GLOBAL RULES" in pack["text"]
    assert "Ask before building" in pack["text"] and "Prefers short answers" in pack["text"]
    assert "Hidden one" not in pack["text"]
    # The Global scope's own pack does not repeat its rules as "global".
    own = (await client.get("/api/projects/global/context")).json()
    assert "GLOBAL RULES" not in own["text"]


async def test_memory_links_are_undirected_kept_on_replacement_and_stay_in_project(
    client: AsyncClient,
) -> None:
    pid = (await client.post("/api/projects", json={"name": "Trailhead"})).json()["id"]
    other = (await client.post("/api/projects", json={"name": "Starling"})).json()["id"]
    base = f"/api/projects/{pid}/memory"
    first = (await client.post(base, json={"type": "decision", "title": "Capacity is 6"})).json()
    second = (
        await client.post(
            base, json={"type": "fact", "title": "Camps hold six", "related": [first["human_id"]]}
        )
    ).json()
    assert [r["human_id"] for r in second["related"]] == [first["human_id"]]
    reread = (await client.get(f"{base}/{first['human_id']}")).json()
    assert [r["human_id"] for r in reread["related"]] == [second["human_id"]]

    # Linking again is harmless; linking to itself is refused.
    again = await client.post(f"{base}/{first['id']}/links", json={"related": second["id"]})
    assert len(again.json()["related"]) == 1
    selfie = await client.post(f"{base}/{first['id']}/links", json={"related": first["id"]})
    assert selfie.status_code == 409

    # Another project's memory cannot be linked.
    foreign = (
        await client.post(f"/api/projects/{other}/memory", json={"type": "fact", "title": "Else"})
    ).json()
    refused = await client.post(f"{base}/{first['id']}/links", json={"related": foreign["id"]})
    assert refused.status_code == 404

    # A replacement keeps the connections.
    replaced = await client.post(f"{base}/{first['id']}/supersede", json={"title": "Capacity is 8"})
    assert replaced.status_code == 201, replaced.text
    assert [r["human_id"] for r in replaced.json()["related"]] == [second["human_id"]]

    gone = await client.delete(f"{base}/{second['id']}/links/{replaced.json()['id']}")
    # The replaced record keeps its own link as history.
    assert gone.status_code == 200
    assert [r["human_id"] for r in gone.json()["related"]] == [first["human_id"]]
    after = (await client.get(f"{base}/{replaced.json()['id']}")).json()
    assert after["related"] == []


async def test_linked_memory_comes_along_in_context(client: AsyncClient) -> None:
    pid = (await client.post("/api/projects", json={"name": "Trailhead"})).json()["id"]
    task = (await client.post(f"/api/projects/{pid}/tasks", json={"title": "Camp capacity"})).json()
    base = f"/api/projects/{pid}/memory"
    linked = (
        await client.post(
            base,
            json={"type": "decision", "title": "Capacity is 6", "task_ids": [task["human_id"]]},
        )
    ).json()
    await client.post(
        base,
        json={"type": "warning", "title": "Save files break above 9", "related": [linked["id"]]},
    )
    pack = (
        await client.get(f"/api/projects/{pid}/context", params={"task": task["human_id"]})
    ).json()
    assert "Save files break above 9" in pack["text"]
    [reason] = [i["reason"] for i in pack["items"] if i["title"] == "Save files break above 9"]
    assert reason.startswith("via ") and f"{linked['human_id']} → relates to → WARN-" in reason


async def test_brief_and_global_rules_over_mcp(database_url: str, tmp_path: Path) -> None:
    repo = tmp_path / "home" / "me" / "game"
    (repo / "src").mkdir(parents=True)
    async with app_client(database_url) as client:
        pid = (
            await client.post("/api/projects", json={"name": "Game", "root_path": str(repo)})
        ).json()["id"]
        await rule(client, "global", "Ask before building")
        await rule(client, pid, "Use tabs in GDScript")
        await rule(client, pid, "Menu text: «Главное меню» → Main menu")

    async with agent(database_url, "codex") as session:
        failed, brief = await call(session, "brain_brief", cwd=str(repo / "src"))
        assert not failed and "Ask before building" in brief and "Use tabs in GDScript" in brief
        assert "PROJECT: Game" in brief
        failed, outside = await call(session, "brain_brief", cwd=str(tmp_path / "elsewhere"))
        assert not failed and "Ask before building" in outside and "PROJECT:" not in outside

        failed, message = await call(
            session, "brain_create_memory", type="rule", title="Be terse", project="global"
        )
        assert failed and "brain_create_proposal" in message
        failed, fact = await call(
            session, "brain_create_memory", type="fact", title="Uses Linux", project="global"
        )
        assert not failed and fact["created"].startswith("FACT")

        failed, first = await call(
            session, "brain_create_memory", type="decision", title="Godot 4", project=pid
        )
        failed, second = await call(
            session,
            "brain_create_memory",
            type="fact",
            title="Uses GDScript",
            project=pid,
            related=[first["created"]],
        )
        assert not failed and second["linked_to"] == [first["created"]]
        failed, third = await call(
            session, "brain_create_memory", type="note", title="Exports nightly", project=pid
        )
        failed, linked = await call(
            session,
            "brain_link_memories",
            memory=third["created"],
            related=[first["created"]],
            project=pid,
        )
        assert not failed and linked["linked_to"] == [first["created"]]

    # The command-line brief for start-up hooks, matched by folder. It is UTF-8 even where the
    # pipe's own encoding cannot hold the text (a Windows code page; ASCII here). The Windows hook
    # passes no --cwd and the brief reads Claude Code's CLAUDE_PROJECT_DIR instead.
    for extra_args, extra_env in (
        (["--cwd", str(repo)], {}),
        ([], {"CLAUDE_PROJECT_DIR": str(repo)}),
    ):
        result = subprocess.run(
            [sys.executable, "-m", "app.mcp", "--brief", *extra_args],
            cwd=BACKEND,
            env={
                **get_default_environment(),  # Windows cannot start Python without SYSTEMROOT
                "PROJECT_BRAIN_DATABASE_URL": database_url,
                "PATH": "/usr/bin:/bin",
                "CLAUDE_CONFIG_DIR": "/nonexistent/claude",
                "CODEX_HOME": "/nonexistent/codex",
                "PYTHONIOENCODING": "ascii",
                **extra_env,
            },
            capture_output=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        output = result.stdout.decode("utf-8")
        assert output.startswith("PROJECT MOAH BRIEF") and "PROJECT: Game" in output
        assert "«Главное меню» → Main menu" in output


def test_global_migration_downgrades_cleanly(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'g.db'}"
    config = Config(str(resource_path("backend/alembic.ini")))
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    db = sqlite3.connect(tmp_path / "g.db")
    db.execute(
        "INSERT INTO memories (id, project_id, human_id, type, title, content, status, importance,"
        " is_pinned, is_locked, ai_visibility, created_at, updated_at) VALUES ('m1', 'global',"
        " 'RULE-001', 'rule', 'Ask first', '', 'active', 'normal', 0, 0, 'always', '2026', '2026')"
    )
    db.commit()
    db.close()
    command.downgrade(config, "0007_proposals")
    db = sqlite3.connect(tmp_path / "g.db")
    assert db.execute("SELECT count(*) FROM projects").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM memories").fetchone()[0] == 0
    columns = [row[1] for row in db.execute("PRAGMA table_info(projects)")]
    assert "kind" not in columns
    db.close()
    command.upgrade(config, "head")

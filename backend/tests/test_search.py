import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient

from app.core.resources import resource_path
from app.db.migrate import upgrade_database
from app.services.search import match_expression
from tests.conftest import app_client

pytestmark = pytest.mark.anyio


async def make(client: AsyncClient, name: str) -> str:
    return (await client.post("/api/projects", json={"name": name})).json()["id"]


async def task(client: AsyncClient, pid: str, **body: object) -> dict:
    response = await client.post(f"/api/projects/{pid}/tasks", json={"title": "Task", **body})
    assert response.status_code == 201, response.text
    return response.json()


async def hits(client: AsyncClient, pid: str | None, q: str, **params: object) -> list[dict]:
    path = f"/api/projects/{pid}/search" if pid else "/api/search"
    response = await client.get(path, params={"q": q, **params})
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_match_expression_quotes_everything() -> None:
    assert match_expression("CAMP-037") == '"CAMP" "037"*'
    assert match_expression('  save* OR "x" NEAR(a b) -') == '"save" "OR" "x" "NEAR" "a" "b"*'
    assert match_expression('-- ; ( ) "') is None
    assert len(match_expression(" ".join("w" * 3 for _ in range(40))).split()) == 12


async def test_index_follows_every_write_and_scope_is_strict(client: AsyncClient) -> None:
    a, b = await make(client, "Project A"), await make(client, "Project B")
    ta = await task(
        client,
        a,
        title="Camp capacity",
        description="Recruitment blocks when full",
        acceptance_criteria=["Migrate old saves"],
        tags=["save-system"],
        prefix="CAMP",
    )
    await task(client, b, title="Camp capacity too", description="Recruitment in B", prefix="CAMP")
    base = f"/api/projects/{a}"

    # Found by title, body, criterion, tag, and human ID, never from the other project.
    for q in ("capacity", "recruitment", "migrate saves", "save-system", "CAMP-001", "camp 001"):
        found = await hits(client, a, q, entity_type="task")
        assert [h["entity_id"] for h in found] == [ta["id"]], q
    assert {h["project_name"] for h in await hits(client, None, "capacity")} == {
        "Project A",
        "Project B",
    }

    # Edits, criteria, tags, status changes, and deletes keep the index current.
    await client.patch(f"{base}/tasks/{ta['id']}", json={"title": "Settlement size", "tags": []})
    assert await hits(client, a, "capacity", entity_type="task") == []
    assert [h["title"] for h in await hits(client, a, "settlement")] == ["Settlement size"]
    assert await hits(client, a, "save-system") == []
    crit = ta["acceptance_criteria"][0]["id"]
    await client.patch(
        f"{base}/tasks/{ta['id']}/criteria/{crit}", json={"description": "Handle legacy"}
    )
    assert await hits(client, a, "migrate") == []
    assert len(await hits(client, a, "legacy")) == 1
    await client.delete(f"{base}/tasks/{ta['id']}/criteria/{crit}")
    assert await hits(client, a, "legacy") == []
    await client.patch(f"{base}/tasks/{ta['id']}", json={"status": "archived"})
    assert await hits(client, a, "settlement") == []
    assert len(await hits(client, a, "settlement", include_archived="true")) == 1
    await client.delete(f"{base}/tasks/{ta['id']}")
    assert await hits(client, a, "settlement", include_archived="true") == []
    assert len(await hits(client, b, "capacity")) == 1


async def test_memory_checkpoints_projects_and_filters(client: AsyncClient) -> None:
    a, b = await make(client, "Trailhead"), await make(client, "Starling")
    mem = lambda pid, **body: client.post(  # noqa: E731
        f"/api/projects/{pid}/memory", json={"type": "decision", "title": "x", **body}
    )
    party5 = (await mem(a, title="Party size is 5", tags=["party"])).json()
    await mem(b, title="Party size is 4")
    idea = (await mem(a, type="idea", title="Party tents", content="Maybe party buffs")).json()
    await client.post(
        f"/api/projects/{a}/checkpoints",
        json={
            "title": "Capacity done",
            "summary": "party limit validated",
            "next_steps": "migrate",
        },
    )

    everything = await hits(client, a, "party")
    assert {(h["entity_type"], h["human_id"]) for h in everything} == {
        ("memory", "DEC-001"),
        ("memory", "IDEA-001"),
        ("checkpoint", None),
    }
    assert [h["memory_type"] for h in await hits(client, a, "party", memory_type="idea")] == [
        "idea"
    ]
    assert {h["entity_type"] for h in await hits(client, a, "party", entity_type="checkpoint")} == {
        "checkpoint"
    }
    assert [h["title"] for h in await hits(client, a, "party", memory_type="decision")] == [
        "Party size is 5"
    ]

    # Replaced records leave normal search and return with history on.
    new = (
        await client.post(
            f"/api/projects/{a}/memory/{party5['id']}/supersede", json={"title": "Party size is 4"}
        )
    ).json()
    titles = [h["title"] for h in await hits(client, a, "size", entity_type="memory")]
    assert titles == ["Party size is 4"] and new["human_id"] == "DEC-002"
    with_history = await hits(client, a, "size", entity_type="memory", include_archived="true")
    assert {h["status"] for h in with_history} == {"active", "superseded"}
    assert [h["status"] for h in await hits(client, a, "size", memory_status="superseded")] == [
        "superseded"
    ]
    await client.post(f"/api/projects/{a}/memory/{idea['id']}/archive")
    assert await hits(client, a, "tents") == []

    # Projects are found only in the explicit all-projects search, and archived ones need a flag.
    assert [h["entity_type"] for h in await hits(client, None, "starling")] == ["project"]
    assert await hits(client, a, "starling", entity_type="project") == []
    await client.post(f"/api/projects/{b}/archive")
    assert await hits(client, None, "starling") == []
    assert len(await hits(client, None, "starling", include_archived="true")) >= 1
    assert [h["project_name"] for h in await hits(client, None, "party")] == ["Trailhead"] * 2


async def test_ranking_is_exact_id_then_title_then_stable(client: AsyncClient) -> None:
    pid = await make(client, "Ranking")
    body_only = await task(
        client, pid, title="Unrelated chore", description="mentions parser once", prefix="Z"
    )
    title_hit = await task(client, pid, title="Parser rewrite", prefix="Z")
    second = await task(client, pid, title="Parser tidy", prefix="Z")
    ids = [h["entity_id"] for h in await hits(client, pid, "parser")]
    assert ids[0] in (title_hit["id"], second["id"]) and ids[-1] == body_only["id"]
    assert ids == [h["entity_id"] for h in await hits(client, pid, "parser")]  # repeatable
    exact = await hits(client, pid, "z-003")
    assert exact[0]["entity_id"] == second["id"]
    assert exact[0]["score"] == exact[0]["score"]  # numeric, not NaN


async def test_safe_queries_pagination_and_empty_input(client: AsyncClient) -> None:
    pid = await make(client, "Safety")
    for index in range(7):
        await task(client, pid, title=f"Item {index} widget")
    for nasty in (
        '"',
        "(",
        "widget AND",
        "NEAR(",
        "a:b",
        "*",
        "' OR 1=1 --",
        "widget; DROP TABLE tasks",
    ):
        response = await client.get(f"/api/projects/{pid}/search", params={"q": nasty})
        assert response.status_code == 200, nasty
    assert (await client.get(f"/api/projects/{pid}/search", params={"q": "   "})).json()[
        "items"
    ] == []
    page = (
        await client.get(
            f"/api/projects/{pid}/search", params={"q": "widget", "limit": 3, "offset": 3}
        )
    ).json()
    assert (page["total"], len(page["items"]), page["offset"]) == (7, 3, 3)
    first = await hits(client, pid, "widget", limit=3)
    assert not {h["entity_id"] for h in first} & {h["entity_id"] for h in page["items"]}
    assert (await client.get("/api/projects/missing/search", params={"q": "x"})).status_code == 404
    assert (await client.get("/api/search", params={"q": "x", "limit": 500})).status_code == 422
    assert "<" not in " ".join(h["snippet"] for h in await hits(client, pid, "widget"))


def test_migration_backfills_existing_records(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'old.db'}"
    config = Config(str(resource_path("backend/alembic.ini")))
    config.attributes["database_url"] = url
    command.upgrade(config, "0004_checkpoints_activity")
    db = sqlite3.connect(tmp_path / "old.db")
    now = "2026-01-01T00:00:00"
    db.execute(
        "INSERT INTO projects (id, name, name_key, slug, status, created_at, updated_at) "
        f"VALUES ('p1', 'Legacy', 'legacy', 'legacy', 'active', '{now}', '{now}')"
    )
    db.execute(
        "INSERT INTO tasks (id, project_id, prefix, number, human_id, title, status, priority, "
        f"sort_order, created_at, updated_at) VALUES ('t1', 'p1', 'OLD', 1, 'OLD-001', 'Old task', "
        f"'todo', 'normal', 0, '{now}', '{now}')"
    )
    db.commit()
    db.close()

    upgrade_database(url)
    db = sqlite3.connect(tmp_path / "old.db")
    rows = db.execute(
        "SELECT entity_type, title FROM search_index WHERE search_index MATCH '\"old\"' "
        "ORDER BY entity_type"
    ).fetchall()
    assert rows == [("task", "Old task")]
    assert (
        db.execute("SELECT count(*) FROM search_index").fetchone()[0] == 3
    )  # project, Global, task
    db.close()

    command.downgrade(config, "0004_checkpoints_activity")
    db = sqlite3.connect(tmp_path / "old.db")
    assert (
        db.execute(
            "SELECT count(*) FROM sqlite_master WHERE name LIKE 'si_%' OR name='search_index'"
        ).fetchone()[0]
        == 0
    )
    db.execute("UPDATE tasks SET title = 'Edited' WHERE id = 't1'")  # triggers are really gone
    db.close()
    upgrade_database(url)


async def test_seeded_database_is_searchable(database_url: str) -> None:
    from app.seed import seed_projects

    seed_projects(database_url)
    async with app_client(database_url) as client:
        assert {h["entity_type"] for h in await hits(client, None, "capacity")} >= {
            "task",
            "memory",
        }
        assert [h["project_name"] for h in await hits(client, None, "party size")] == ["Starling"]


def test_migration_adds_pending_flag_to_existing_memories(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'old.db'}"
    config = Config(str(resource_path("backend/alembic.ini")))
    config.attributes["database_url"] = url
    command.upgrade(config, "0010_app_settings")
    db = sqlite3.connect(tmp_path / "old.db")
    now = "2026-01-01T00:00:00"
    db.execute(
        "INSERT INTO projects (id, name, name_key, slug, status, created_at, updated_at) "
        f"VALUES ('p1', 'Legacy', 'legacy', 'legacy', 'active', '{now}', '{now}')"
    )
    db.execute(
        "INSERT INTO memories (id, project_id, human_id, type, title, content, status, "
        "importance, is_pinned, is_locked, ai_visibility, created_at, updated_at) VALUES "
        "('m1', 'p1', 'BUG-001', 'bug', 'Old bug', '', 'active', 'normal', 0, 0, "
        f"'relevant_only', '{now}', '{now}')"
    )
    db.commit()
    db.close()

    upgrade_database(url)
    db = sqlite3.connect(tmp_path / "old.db")
    assert db.execute("SELECT is_resolved FROM memories WHERE id = 'm1'").fetchone() == (0,)
    db.close()

    command.downgrade(config, "0010_app_settings")
    db = sqlite3.connect(tmp_path / "old.db")
    columns = [row[1] for row in db.execute("PRAGMA table_info(memories)")]
    assert "is_resolved" not in columns
    assert db.execute("SELECT title FROM memories").fetchone() == ("Old bug",)
    db.close()

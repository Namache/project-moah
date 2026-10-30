"""Drives the real MCP server as a subprocess over stdio, the way an agent would."""

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from httpx import AsyncClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tests.conftest import app_client

pytestmark = pytest.mark.anyio
BACKEND = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def agent(database_url: str, name: str = "claude", *extra: str):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp", "--agent", name, *extra],
        cwd=str(BACKEND),
        env={
            "PROJECT_BRAIN_DATABASE_URL": database_url,
            "PATH": "/usr/bin:/bin",
            # Never read the real agents' logs from tests.
            "CLAUDE_CONFIG_DIR": "/nonexistent/claude",
            "CODEX_HOME": "/nonexistent/codex",
            "PROJECT_BRAIN_EXPLORE": "0",  # packs are compared exactly
        },
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


async def call(session: ClientSession, tool: str, **args: object) -> tuple[bool, object]:
    result = await session.call_tool(tool, args)
    text = "".join(getattr(block, "text", "") for block in result.content)
    if result.is_error:
        return True, text
    try:
        return False, result.structured_content.get(
            "result", result.structured_content
        ) if result.structured_content else json.loads(text)
    except (ValueError, AttributeError):
        return False, text


async def seed(client: AsyncClient, tmp_path: Path) -> dict:
    root_a, root_b = tmp_path / "trailhead", tmp_path / "trailhead-experimental"
    (root_a / "src").mkdir(parents=True)
    root_b.mkdir()
    a = (
        await client.post("/api/projects", json={"name": "Trailhead", "root_path": str(root_a)})
    ).json()["id"]
    b = (
        await client.post("/api/projects", json={"name": "Starling", "root_path": str(root_b)})
    ).json()["id"]
    await client.post(
        "/api/projects", json={"name": "Twin One", "root_path": str(tmp_path / "shared")}
    )
    await client.post(
        "/api/projects", json={"name": "Twin Two", "root_path": str(tmp_path / "shared")}
    )
    (tmp_path / "shared").mkdir()
    task = (
        await client.post(
            f"/api/projects/{a}/tasks",
            json={
                "title": "Camp capacity",
                "prefix": "CAMP",
                "next_action": "Add migration",
                "acceptance_criteria": ["Track", "Migrate"],
            },
        )
    ).json()
    await client.post(f"/api/projects/{a}/tasks/{task['id']}/start")
    locked = (
        await client.post(
            f"/api/projects/{a}/memory",
            json={
                "type": "decision",
                "title": "Capacity is 6",
                "content": "6",
                "is_locked": True,
                "task_ids": [task["id"]],
            },
        )
    ).json()
    await client.post(
        f"/api/projects/{b}/memory",
        json={"type": "decision", "title": "Party size is 4", "content": "four"},
    )
    return {
        "a": a,
        "b": b,
        "task": task,
        "locked": locked,
        "root_a": root_a,
        "root_b": root_b,
        "shared": tmp_path / "shared",
    }


async def test_tools_are_small_documented_and_hide_internals(database_url: str) -> None:
    async with agent(database_url) as session:
        tools = {t.name: t for t in (await session.list_tools()).tools}
        assert len(tools) == 25 and all(n.startswith("brain_") for n in tools)
        reads = {
            "brain_brief",
            "brain_second_opinion",
            "brain_list_projects",
            "brain_project_state",
            "brain_context_pack",
            "brain_get_task",
            "brain_view_images",
            "brain_list_tasks",
            "brain_search",
            "brain_get_related",
            "brain_changed_files",
            "brain_links",
            "brain_shelves",
            "brain_link_review",
        }
        for name, tool in tools.items():
            assert tool.description, name
            assert "session" not in json.dumps(tool.input_schema), name
            assert bool(tool.annotations and tool.annotations.read_only_hint) == (name in reads), (
                name
            )


async def test_project_detection_never_guesses(database_url: str, tmp_path: Path) -> None:
    async with app_client(database_url) as client:
        world = await seed(client, tmp_path)
    async with agent(database_url) as session:
        error, text = await call(session, "brain_project_state", cwd=str(world["root_a"] / "src"))
        assert (
            not error
            and text["project"]["name"] == "Trailhead"
            and text["project"]["found_by"] == "working directory"
        )
        assert text["current_focus"]["human_id"] == "CAMP-001"
        # A sibling folder with a similar name is a different project, not a prefix match.
        error, text = await call(session, "brain_project_state", cwd=str(world["root_b"]))
        assert text["project"]["name"] == "Starling"
        error, text = await call(session, "brain_project_state", cwd=str(world["shared"]))
        assert (
            error
            and "Unable to safely determine" in text
            and "Twin One" in text
            and "Twin Two" in text
        )
        error, text = await call(session, "brain_project_state", cwd=str(tmp_path))
        assert error and "Specify project explicitly" in text
        error, text = await call(session, "brain_project_state", project="nope")
        assert error and "Known projects" in text
        error, text = await call(session, "brain_project_state", project="starling")
        assert not error and text["project"]["found_by"] == "project argument"
    async with agent(
        database_url, "codex", "--project", "trailhead"
    ) as session:  # configured default
        error, text = await call(session, "brain_project_state", cwd=str(tmp_path))
        assert not error and text["project"]["found_by"] == "server setting"


async def test_reads_stay_in_the_chosen_project(database_url: str, tmp_path: Path) -> None:
    async with app_client(database_url) as client:
        world = await seed(client, tmp_path)
    async with agent(database_url) as session:
        error, pack = await call(
            session, "brain_context_pack", task="CAMP-001", project="trailhead"
        )
        assert (
            not error
            and "Capacity is 6" in pack
            and "Add migration" in pack
            and "Party size is 4" not in pack
        )
        error, tasks = await call(session, "brain_list_tasks", project="trailhead")
        assert [t["id"] for t in tasks] == ["CAMP-001"] and tasks[0]["criteria"] == "0/2"
        error, found = await call(session, "brain_search", query="party", project="trailhead")
        assert not error and found["total"] == 0
        error, found = await call(session, "brain_search", query="party", scope="all")
        assert found["results"][0]["project_name"] == "Starling"
        assert (await call(session, "brain_search", query="x", scope="galaxy"))[0] is True
        error, related = await call(
            session, "brain_get_related", task="CAMP-001", project="trailhead"
        )
        assert [m["id"] for m in related["memory"]] == ["DEC-001"] and related["memory"][0][
            "locked"
        ] is True
        assert (
            await call(session, "brain_get_task", task=world["task"]["id"], project="starling")
        )[0] is True  # not in that project


async def test_writes_respect_locks_and_attribute_the_agent(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        world = await seed(client, tmp_path)
        pid = world["a"]
        async with agent(database_url, "claude") as session:
            error, text = await call(
                session, "brain_update_memory", memory="DEC-001", content="8", project="trailhead"
            )
            assert error and "locked" in text and "brain_create_proposal" in text
            error, out = await call(
                session,
                "brain_create_proposal",
                project="trailhead",
                proposal_type="update_memory",
                target="DEC-001",
                payload={"content": "8"},
                reason="Playtests need 8",
            )
            assert (
                not error and out["proposal"] == "PROP-001" and out["changes"] == ["Content: 6 → 8"]
            )
            error, out = await call(
                session,
                "brain_create_memory",
                project="trailhead",
                type="idea",
                title="Tents",
                content="maybe",
            )
            assert not error and out["created"] == "IDEA-001"
            error, out = await call(
                session,
                "brain_update_task",
                task="CAMP-001",
                project="trailhead",
                next_action="Write tests",
                status="review",
            )
            assert not error and out["applied"] is True
            error, out = await call(
                session,
                "brain_update_task",
                task="CAMP-001",
                project="trailhead",
                status="completed",
                reason="All done",
            )
            assert not error and out["applied"] is False and out["proposal"] == "PROP-002"
            error, out = await call(
                session,
                "brain_create_checkpoint",
                project="trailhead",
                task="CAMP-001",
                title="Tests added",
                summary="Wrote tests",
                next_steps="Review",
            )
            assert not error and out["task"] == "CAMP-001"
            error, out = await call(
                session,
                "brain_create_task",
                project="trailhead",
                title="Follow up",
                status="completed",
            )
            assert error  # tasks never start as completed
            error, out = await call(
                session,
                "brain_create_task",
                project="trailhead",
                title="Follow up",
                prefix="CAMP",
                acceptance_criteria=["Do it"],
            )
            assert not error and out["created"] == "CAMP-002"

        assert (await client.get(f"/api/projects/{pid}/memory/DEC-001")).json()[
            "content"
        ] == "6"  # lock held
        assert (await client.get(f"/api/projects/{pid}/tasks/CAMP-001")).json()[
            "status"
        ] == "review"  # not completed
        memory = (await client.get(f"/api/projects/{pid}/memory/IDEA-001")).json()
        assert (memory["source_type"], memory["source_reference"], memory["is_locked"]) == (
            "agent",
            "claude",
            False,
        )
        actors = {
            (e["event_type"], e["actor_type"])
            for e in (await client.get(f"/api/projects/{pid}/activity")).json()
        }
        assert {
            ("PROPOSAL_CREATED", "claude"),
            ("CHECKPOINT_CREATED", "claude"),
            ("MEMORY_CREATED", "claude"),
        } <= actors
        assert ("TASK_CREATED", "claude") in actors
        assert any(
            who == "claude" and kind.startswith("TASK_") and kind != "TASK_CREATED"
            for kind, who in actors
        )
        cp = (await client.get(f"/api/projects/{pid}/checkpoints/latest")).json()
        assert cp["agent"] == "claude"
        # The agent's writes never reached the other project.
        assert (await client.get(f"/api/projects/{world['b']}/proposals")).json() == []


async def test_archived_projects_are_read_only_for_agents(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        world = await seed(client, tmp_path)
        await client.post(f"/api/projects/{world['b']}/archive")
    async with agent(database_url) as session:
        assert (await call(session, "brain_list_tasks", project="starling"))[0] is False
        error, text = await call(
            session, "brain_create_memory", project="starling", type="note", title="x"
        )
        assert error and "archived" in text


async def test_agents_cannot_see_hidden_memory_or_bypass_review(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        world = await seed(client, tmp_path)
        a = world["a"]
        await client.post(
            f"/api/projects/{a}/memory",
            json={"type": "note", "title": "Secret zebra note", "ai_visibility": "hidden"},
        )
        await client.post(
            f"/api/projects/{a}/memory",
            json={"type": "bug", "title": "Locked crash", "is_locked": True},
        )
        await client.post(
            "/api/projects/global/memory", json={"type": "rule", "title": "Always write tests"}
        )
    async with agent(database_url) as session:
        error, found = await call(session, "brain_search", project="trailhead", query="zebra")
        assert not error and found["total"] == 0
        error, found = await call(session, "brain_search", scope="all", query="zebra")
        assert not error and found["total"] == 0

        error, text = await call(
            session, "brain_update_memory", project="trailhead", memory="BUG-001", resolved=True
        )
        assert error and "locked" in text.lower()

        for tool, extra in (
            ("brain_supersede_memory", {"title": "Never write tests"}),
            ("brain_update_memory", {"content": "Unless busy"}),
        ):
            error, text = await call(session, tool, project="global", memory="RULE-001", **extra)
            assert error and "brain_create_proposal" in text

        error, text = await call(
            session, "brain_link_memories", project="trailhead", memory="BUG-001", related=[]
        )
        assert error and "at least one" in text

    async with app_client(database_url) as client:
        task = world["task"]["human_id"]
        done = await client.patch(
            f"/api/projects/{world['a']}/tasks/{task}", json={"status": "completed"}
        )
        assert done.status_code == 200
    async with agent(database_url) as session:
        error, _ = await call(
            session,
            "brain_update_task",
            project="trailhead",
            task=task,
            status="completed",
            priority="low",
        )
        assert error
        error, detail = await call(session, "brain_get_task", project="trailhead", task=task)
        assert detail["priority"] != "low"  # nothing was half-applied


async def test_an_agent_cannot_call_itself_human(database_url: str) -> None:
    from sqlalchemy.orm import sessionmaker

    from app.mcp.server import build_server

    with pytest.raises(ValueError):
        build_server(sessionmaker(), agent=" Human ")


async def test_agents_link_records_and_shape_shelves(database_url: str) -> None:
    async with app_client(database_url) as client:
        pid = (await client.post("/api/projects", json={"name": "Trailhead"})).json()["id"]
        base = f"/api/projects/{pid}"
        task = (
            await client.post(f"{base}/tasks", json={"title": "Fix item duplication on load"})
        ).json()
        mine = (await client.post(f"{base}/memory", json={"type": "fact", "title": "A"})).json()
        rule = (await client.post(f"{base}/memory", json={"type": "rule", "title": "B"})).json()
        await client.post(
            f"{base}/links",
            json={
                "source": mine["human_id"],
                "relationship": "explains",
                "target": rule["human_id"],
            },
        )
    async with agent(database_url) as session:
        failed, made = await call(
            session,
            "brain_link",
            source=task["human_id"],
            relationship="constrained_by",
            target=rule["human_id"],
            strength=0.9,
            project=pid,
        )
        assert not failed and made["confidence"] == 0.8  # an agent's link is trusted less
        failed, seen = await call(session, "brain_links", node=rule["human_id"], project=pid)
        assert not failed
        assert {(x["relationship"], x["node"]) for x in seen["links"]} == {
            ("constrains", f"task:{task['human_id']}"),
            ("explained_by", f"memory:{mine['human_id']}"),
        }
        # A person's link is not the agent's to remove.
        failed, text = await call(
            session,
            "brain_link",
            source=mine["human_id"],
            relationship="explains",
            target=rule["human_id"],
            remove=True,
            project=pid,
        )
        assert failed and "brain_create_proposal" in text
        failed, _ = await call(
            session,
            "brain_link",
            source=task["human_id"],
            relationship="constrained_by",
            target=rule["human_id"],
            remove=True,
            project=pid,
        )
        assert not failed

        failed, shelf = await call(
            session,
            "brain_update_shelf",
            shelf="Inventory",
            keywords=["item", "loot"],
            add=[rule["human_id"]],
            project=pid,
        )
        assert not failed and shelf["records"] == 1
        failed, woke = await call(session, "brain_shelves", task=task["human_id"], project=pid)
        assert not failed and woke["activation"][0]["shelf"] == "Inventory"
        assert woke["activation"][0]["active"] is True
        failed, text = await call(session, "brain_context_pack", task=task["human_id"], project=pid)
        assert not failed and "ACTIVE SHELVES\nInventory" in text and "B" in text


async def test_agent_packs_skip_global_rules_the_brief_gave(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        await seed(client, tmp_path)
        await client.post(
            "/api/projects/global/memory",
            json={"type": "rule", "title": "Ask before building", "content": "Wait for a yes."},
        )
    async with agent(database_url) as session:
        error, brief = await call(session, "brain_brief", project="trailhead")
        assert not error and "Ask before building" in brief
        error, pack = await call(
            session, "brain_context_pack", task="CAMP-001", project="trailhead"
        )
        assert not error and "Ask before building" not in pack and "GLOBAL RULES" not in pack
        assert "already in your brief" in pack
        error, pack = await call(
            session,
            "brain_context_pack",
            task="CAMP-001",
            project="trailhead",
            global_rules=True,
        )
        assert not error and "Ask before building" in pack


async def test_projects_file_records_on_one_shared_tree(database_url: str) -> None:
    async with app_client(database_url) as client:
        a = (await client.post("/api/projects", json={"name": "Trailhead"})).json()["id"]
        b = (await client.post("/api/projects", json={"name": "Taskbar"})).json()["id"]
        boss = (
            await client.post(
                f"/api/projects/{a}/memory",
                json={"type": "decision", "title": "Bosses telegraph attacks"},
            )
        ).json()
        await client.post(
            f"/api/projects/{b}/memory",
            json={"type": "note", "title": "Dragon fights", "tags": ["Combat"]},
        )
        task = (await client.post(f"/api/projects/{a}/tasks", json={"title": "Tune combat"})).json()
    async with agent(database_url) as session:
        path = "Knowledge > Game development > Game design > Game mechanics > Combat"
        failed, shelf = await call(
            session,
            "brain_update_shelf",
            shelf=path,
            shared=True,
            keywords=["boss", "fight"],
            add=[boss["human_id"]],
            project=a,
        )
        assert not failed and shelf == {
            "shelf": path,
            "shared": True,
            "keywords": ["boss", "fight"],
            "records": 1,
        }
        # Each project sees only its own records on the shared tree; tags count there too.
        _, mine = await call(session, "brain_shelves", shelf="Combat", project=a)
        _, theirs = await call(session, "brain_shelves", shelf="Combat", project=b)
        assert [m.split(" ", 1)[1] for m in mine["members"]] == ["Bosses telegraph attacks"]
        assert [m.split(" ", 1)[1] for m in theirs["members"]] == ["Dragon fights"]
        _, tree = await call(session, "brain_shelves", project=a)
        assert {"shelf": path, "records": 1, "keywords": ["boss", "fight"]} in tree["shared_tree"]

        # Work that names the domain wakes the shared shelf, and its records come along.
        failed, text = await call(session, "brain_context_pack", task=task["human_id"], project=a)
        assert not failed and f"Global: {path}" in text and "Bosses telegraph" in text
        assert "Dragon fights" not in text

        # A new record is filed on the deepest shelf its words name, or where it is told.
        _, made = await call(
            session, "brain_create_memory", type="note", title="Boss fight pacing", project=a
        )
        assert made["shelf"] == f"shared: {path}" and made["filed"].startswith("automatically")
        _, mine = await call(session, "brain_shelves", shelf="Combat", project=a)
        assert "Boss fight pacing" in " ".join(mine["members"])
        _, made = await call(session, "brain_create_task", title="Boss fight timer", project=a)
        assert made["shelf"] == f"shared: {path}"
        _, made = await call(
            session,
            "brain_create_memory",
            type="note",
            title="Boss fight arenas",
            shelf="Combat",
            project=a,
        )
        assert made["shelf"] == path

        failed, gone = await call(
            session, "brain_update_shelf", shelf="Combat", shared=True, delete=True, project=a
        )
        assert not failed and gone == {"deleted": path}
        _, tree = await call(session, "brain_shelves", project=a)
        assert path not in [s["shelf"] for s in tree["shared_tree"]]

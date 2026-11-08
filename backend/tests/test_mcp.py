"""Drives the real MCP server as a subprocess over stdio, the way an agent would."""

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from httpx import AsyncClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client
from mcp.types import Implementation

from tests.conftest import app_client

pytestmark = pytest.mark.anyio
BACKEND = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def agent(
    database_url: str,
    name: str = "claude",
    *extra: str,
    start: tuple[str, ...] = ("-m", "app.mcp"),
    client: str | None = None,
):
    params = StdioServerParameters(
        command=sys.executable,
        args=[*start, "--agent", name, *extra],
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
    info = Implementation(name=client, version="1.0") if client else None
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write, client_info=info) as session,
    ):
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
        assert len(tools) == 29 and all(n.startswith("brain_") for n in tools)
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
            # A finished task waits for the person in review, and the agent is asked for its
            # own report.
            assert not error and out["applied"] is True and out["status"] == "review"
            assert 'brain_submit_review(task="CAMP-001"' in out["next"]
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
        # The rule wakes with its shelf. An agent's pack leaves out the shelf line (and the rule,
        # which its brief lists); explain=true shows both.
        failed, _ = await call(session, "brain_brief", project=pid)
        assert not failed
        failed, text = await call(session, "brain_context_pack", task=task["human_id"], project=pid)
        assert not failed and "ACTIVE SHELVES" not in text and rule["human_id"] not in text
        failed, text = await call(
            session,
            "brain_context_pack",
            task=task["human_id"],
            project=pid,
            explain=True,
            global_rules=True,
        )
        assert not failed and "ACTIVE SHELVES\nInventory" in text and rule["human_id"] in text


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
        assert "~" not in pack and "operation coding" not in pack  # sizes are for explain=true
        error, pack = await call(
            session,
            "brain_context_pack",
            task="CAMP-001",
            project="trailhead",
            explain=True,
            full=True,
        )
        assert not error and "already in your brief" in pack and "operation coding" in pack
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
        failed, text = await call(
            session, "brain_context_pack", task=task["human_id"], project=a, explain=True
        )
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


async def test_repeat_packs_in_a_session_send_only_what_is_new(
    database_url: str, tmp_path: Path
) -> None:
    import subprocess

    async with app_client(database_url) as client:
        await seed(client, tmp_path)
    async with agent(database_url) as session:
        error, first = await call(
            session, "brain_context_pack", task="CAMP-001", project="trailhead"
        )
        assert not error and "CURRENT TASK" in first and "brain_retrieval_feedback" in first
        error, again = await call(
            session, "brain_context_pack", task="CAMP-001", project="trailhead"
        )
        assert not error and again.startswith("Nothing new since R-")
        assert "brain_retrieval_feedback" not in again and len(again) < len(first) / 3
        error, full = await call(
            session, "brain_context_pack", task="CAMP-001", project="trailhead", full=True
        )
        assert not error and "CURRENT TASK" in full

        # The start-up hook runs when a session starts, is cleared or is compacted: the
        # running server must not answer "nothing new" to an agent that lost its context.
        subprocess.run(
            [sys.executable, "-m", "app.mcp", "--brief", "--cwd", str(tmp_path)],
            cwd=str(BACKEND),
            env={
                **get_default_environment(),  # Windows cannot start Python without SYSTEMROOT
                "PROJECT_BRAIN_DATABASE_URL": database_url,
                "PATH": "/usr/bin:/bin",
            },
            check=True,
            capture_output=True,
        )
        error, after_clear = await call(
            session, "brain_context_pack", task="CAMP-001", project="trailhead"
        )
        assert not error and "CURRENT TASK" in after_clear

        error, _ = await call(session, "brain_brief", project="trailhead")
        error, after_brief = await call(
            session, "brain_context_pack", task="CAMP-001", project="trailhead"
        )
        assert not error and "CURRENT TASK" in after_brief


async def test_search_answers_plain_questions_and_new_records_show_lookalikes(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        a = (await seed(client, tmp_path))["a"]
        for type_, title, content in (
            ("decision", "Weeks start on Monday", ""),
            ("decision", "The current week can't break a weekly streak", ""),
            ("fact", "Monday is the quietest day", ""),
            # Shares the words only in its content: not the same thing said twice.
            ("decision", "Streak colours", "Green once a week starts, from Monday on."),
            *(("fact", f"Day {n} reward", "") for n in range(6)),
        ):
            made = await client.post(
                f"/api/projects/{a}/memory",
                json={"type": type_, "title": title, "content": content},
            )
            assert made.status_code == 201, made.text
    question = "which day does the week start"
    async with agent(database_url) as session:
        # No record has every word, so any word counts, and the result says so.
        for scope in ("project", "all"):
            error, found = await call(
                session, "brain_search", query=question, project="trailhead", scope=scope
            )
            assert not error and found["matched"].startswith("any word"), found
            assert "Weeks start on Monday" in [r["title"] for r in found["results"]]
            # Checking before a question stays cheap: the best few, without repeated fields.
            assert found["total"] > 5 and len(found["results"]) == 5
            assert ("project_name" in found["results"][0]) == (scope == "all")
            assert "status" not in found["results"][0]
        error, found = await call(
            session, "brain_search", query="weeks monday", project="trailhead"
        )
        assert not error and found["total"] == 1 and "matched" not in found
        error, found = await call(session, "brain_search", query="zebra", project="trailhead")
        assert not error and found == {"total": 0, "results": []}

        error, created = await call(
            session,
            "brain_create_memory",
            type="decision",
            title="The week starts on Monday",
            project="trailhead",
        )
        assert not error
        lookalikes = created["possible_duplicates"]
        assert "Weeks start on Monday" in [d["title"] for d in lookalikes]
        assert created["created"] not in [d["id"] for d in lookalikes]
        assert "Monday is the quietest day" not in [d["title"] for d in lookalikes]  # a fact
        # One shared title word is not enough, and words in the content do not count.
        assert "The current week can't break a weekly streak" not in [
            d["title"] for d in lookalikes
        ]
        assert "Streak colours" not in [d["title"] for d in lookalikes]
        assert len(lookalikes) <= 3 and "brain_supersede_memory" in created["duplicates_hint"]
        error, created = await call(
            session, "brain_create_memory", type="decision", title="Zebra crossings", project=a
        )
        assert not error and "possible_duplicates" not in created
        assert "duplicates_hint" not in created


async def test_agents_archive_and_restore_tasks_only_on_request(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        world = await seed(client, tmp_path)
        a = world["a"]
        made = []
        for title, status in (
            ("Ship the map screen", "completed"),
            ("Write the save format", "completed"),
            ("Old idea", "backlog"),
            ("Fix the jump", "in_progress"),
        ):
            row = (await client.post(f"/api/projects/{a}/tasks", json={"title": title})).json()
            await client.patch(
                f"/api/projects/{a}/tasks/{row['human_id']}", json={"status": status}
            )
            made.append(row["human_id"])
        done1, done2, idea, open_task = made
    async with agent(database_url) as session:
        # The person's words are required: no request, no archive.
        error, text = await call(
            session, "brain_archive_tasks", project="trailhead", tasks=[idea], person_asked=" "
        )
        assert error and "brain_create_proposal" in text
        error, text = await call(
            session, "brain_archive_tasks", project="trailhead", person_asked="tidy up"
        )
        assert error and "all_done" in text

        error, result = await call(
            session,
            "brain_archive_tasks",
            project="trailhead",
            all_done=True,
            tasks=[idea, "NOPE-999"],
            person_asked="archive the done tasks and the old idea",
        )
        assert not error
        assert {r["task"] for r in result["archived"]} == {done1, done2, idea}
        assert result["skipped"] == [{"task": "NOPE-999", "why": "not found in this project"}]

        error, again = await call(
            session, "brain_archive_tasks", project="trailhead", tasks=[idea], person_asked="again"
        )
        assert (
            not error and again["count"] == 0 and again["skipped"][0]["why"] == "already archived"
        )

        error, back = await call(
            session,
            "brain_archive_tasks",
            project="trailhead",
            tasks=[done1, idea, open_task],
            restore=True,
            person_asked="bring those two back",
        )
        assert not error
        assert {(r["task"], r["status"]) for r in back["restored"]} == {
            (done1, "completed"),
            (idea, "backlog"),
        }
        assert back["skipped"] == [{"task": open_task, "why": "not archived (in_progress)"}]
        error, text = await call(
            session,
            "brain_archive_tasks",
            project="trailhead",
            all_done=True,
            restore=True,
            person_asked="restore all",
        )
        assert error and "Restore names its tasks" in text

    async with app_client(database_url) as client:
        tasks = {
            t["human_id"]: t["status"]
            for t in (await client.get(f"/api/projects/{a}/tasks?include_archived=true")).json()
        }
        assert tasks[done2] == "archived" and tasks[done1] == "completed"
        assert tasks[open_task] == "in_progress"
        events = (await client.get(f"/api/projects/{a}/activity")).json()
        archived = [e for e in events if e["event_type"] == "TASK_ARCHIVED"]
        assert archived and all(
            e["actor_name"] == "claude"
            and e["metadata"]["asked_by_person"] == "archive the done tasks and the old idea"
            for e in archived
        )
        # Nothing became a proposal: the person asked, so it was done.
        assert (await client.get(f"/api/projects/{a}/proposals")).json() == []


async def test_agents_archive_and_restore_memory_only_on_request(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        world = await seed(client, tmp_path)
        a = world["a"]
        rule = (
            await client.post(
                "/api/projects/global/memory",
                json={"type": "rule", "title": "Use tabs", "content": "Old style rule"},
            )
        ).json()["human_id"]
        note = (
            await client.post(
                f"/api/projects/{a}/memory", json={"type": "note", "title": "Try the blue theme"}
            )
        ).json()["human_id"]
        shut = (
            await client.post(
                f"/api/projects/{a}/memory",
                json={"type": "decision", "title": "Keep saves local", "is_locked": True},
            )
        ).json()["human_id"]
    async with agent(database_url) as session:
        error, text = await call(
            session, "brain_archive_memories", project="global", memories=[rule], person_asked=""
        )
        assert error and "brain_create_proposal" in text

        error, result = await call(
            session,
            "brain_archive_memories",
            project="global",
            memories=[rule],
            person_asked="archive the tabs rule, it's outdated",
        )
        assert not error and result["archived"][0]["memory"] == rule

        error, result = await call(
            session,
            "brain_archive_memories",
            project="trailhead",
            memories=[note, shut, "NOTE-999"],
            person_asked="archive the blue theme note and the saves decision",
        )
        assert not error and [r["memory"] for r in result["archived"]] == [note]
        assert {s["memory"] for s in result["skipped"]} == {shut, "NOTE-999"}
        assert any("locked" in s["why"] for s in result["skipped"])

        error, back = await call(
            session,
            "brain_archive_memories",
            project="global",
            memories=[rule],
            restore=True,
            person_asked="bring the tabs rule back",
        )
        assert not error and back["restored"][0]["memory"] == rule

    async with app_client(database_url) as client:
        assert (await client.get(f"/api/projects/global/memory/{rule}")).json()["status"] == (
            "active"
        )
        events = (await client.get(f"/api/projects/{a}/activity")).json()
        archived = [e for e in events if e["event_type"] == "MEMORY_ARCHIVED"]
        assert len(archived) == 1
        assert archived[0]["metadata"]["asked_by_person"].startswith("archive the blue theme")


# The Flatpak's MCP server, as an agent starts it, with a stand-in for /.flatpak-info.
AS_FLATPAK = (
    "import sys; from pathlib import Path; from app.services import agent_connect; "
    "agent_connect.FLATPAK_INFO = Path(sys.argv[1]); from app.mcp.cli import main; "
    "sys.exit(main(sys.argv[2:]))"
)


async def test_an_old_flatpak_connection_hears_once_how_to_refresh_it(
    database_url: str, tmp_path: Path
) -> None:
    async with app_client(database_url) as client:
        await seed(client, tmp_path)
    info = tmp_path / "flatpak-info"
    info.write_text("[Context]\nfilesystems=~/.claude/projects:ro;~/.codex/sessions:ro;\n")
    start = ("-c", AS_FLATPAK, str(info))
    # Connected by 0.3.0 or older: no --session-id, and the container kept the environment.
    async with agent(database_url, "claude", start=start, client="claude-code") as session:
        # An empty list of rows has no room for it: the answer stays as it is, the notice waits.
        error, tasks = await call(
            session, "brain_list_tasks", project="trailhead", status=["review"]
        )
        assert not error and tasks == [], tasks
        error, task = await call(session, "brain_get_task", task="CAMP-001", project="trailhead")
        assert not error and task["moah_connection"].startswith("MOAH CONNECTION IS OUT OF DATE")
        assert "--filesystem=home" in task["moah_connection"] and task["title"] == "Camp capacity"
        error, brief = await call(session, "brain_brief", project="trailhead")
        assert not error and "MOAH CONNECTION" not in brief
    # Connect's current entry passes the session, even an empty one: nothing to refresh.
    async with agent(
        database_url, "claude", "--session-id", "", start=start, client="claude-code"
    ) as session:
        error, task = await call(session, "brain_get_task", task="CAMP-001", project="trailhead")
        assert not error and "moah_connection" not in task
    # The Claude desktop app starts it the same way, but Connect never changes its entry.
    async with agent(database_url, "claude", start=start, client="claude-ai") as session:
        error, task = await call(session, "brain_get_task", task="CAMP-001", project="trailhead")
        assert not error and "moah_connection" not in task

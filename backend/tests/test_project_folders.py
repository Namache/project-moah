"""Matching an agent's working folder to its project: a project's own folder, the folders Sync
from agents linked to it, and its Git remote.

The project here is set up the way a real one looks half way through: rules, a decision, a
task in progress with a checkpoint, and rules filed on a small shelf tree, so the brief has
something to carry and a missed match shows.
"""

import json
import sys
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.db.session import make_engine, make_session_factory
from app.mcp.projects import ProjectChoiceError, resolve_project
from app.services.brief import build_brief
from app.services.folders import normalize_remote, repository_remote
from tests.conftest import app_client

pytestmark = pytest.mark.anyio
linux_folders = pytest.mark.skipif(sys.platform == "win32", reason="Linux folder layout")

# What the Flatpak file picker hands the app for a folder it has no access to.
PORTAL = "/run/user/1000/doc/Xy12AbCd/Ember Road - Tactics RPG"
REAL = "/home/me/Desktop/Ember Road - Tactics RPG"


@pytest.fixture
def logs(tmp_path: Path, monkeypatch) -> dict:
    claude, codex = tmp_path / "claude", tmp_path / "codex"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    monkeypatch.setenv("CODEX_HOME", str(codex))
    monkeypatch.setenv("HOME", "/home/me")
    count = {"n": 0}

    def session(cwd: str) -> None:
        count["n"] += 1
        path = claude / "projects" / cwd.replace("/", "-") / f"s{count['n']}.jsonl"
        line = {"type": "user", "cwd": cwd, "timestamp": "2026-11-01T09:00:00Z"}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"type": "summary"}) + "\n" + json.dumps(line) + "\n")

    return {"session": session}


async def post(client: AsyncClient, url: str, body: dict, code: int = 201) -> dict:
    response = await client.post(url, json=body)
    assert response.status_code == code, response.text
    return response.json()


async def seed_game(client: AsyncClient, root: str | None, name: str = "Ember Road") -> str:
    """A tactics game half way through: rules on art and balance shelves, a decision, a task in
    progress and the checkpoint the last session left."""
    body = {"name": name, **({"root_path": root} if root else {})}
    pid = (await post(client, "/api/projects", body))["id"]
    base = f"/api/projects/{pid}"
    art = await post(
        client,
        f"{base}/memory",
        {
            "type": "rule",
            "title": "Check sprites zoomed in before showing them",
            "content": "Limbs attached, no stray pixels, nothing cut off at the cell edge.",
            "importance": "high",
        },
    )
    balance = await post(
        client,
        f"{base}/memory",
        {
            "type": "rule",
            "title": "No stat may drop when a unit evolves",
            "content": "Each evolution step is stronger but moderate.",
        },
    )
    await post(
        client,
        f"{base}/memory",
        {"type": "decision", "title": "Healers revive at 35% health after a battle"},
    )
    task = await post(
        client,
        f"{base}/tasks",
        {"title": "Rebalance the second island", "prefix": "EMB", "status": "in_progress"},
    )
    await post(
        client,
        f"{base}/checkpoints",
        {
            "title": "Island 2 enemies retuned",
            "agent": "claude",
            "task_id": task["id"],
            "remaining_work": "Run the balance sim for ascension 0 and 1.",
        },
    )
    knowledge = await post(client, f"{base}/shelves", {"name": "Game development"})
    for shelf_name, record in (("Art", art), ("Balance", balance)):
        shelf = await post(
            client, f"{base}/shelves", {"name": shelf_name, "parent": knowledge["id"]}
        )
        await post(
            client,
            f"{base}/shelves/{shelf['id']}/members",
            {"node": f"memory:{record['id']}"},
            200,
        )
    return pid


def brief_from(database_url: str, cwd: str) -> str:
    """The start-up brief an agent starting in ``cwd`` gets, picked as the hook picks it."""
    engine = make_engine(database_url)
    try:
        with make_session_factory(engine)() as session:
            try:
                found, _ = resolve_project(session, None, cwd)
                return build_brief(session, found)
            except ProjectChoiceError as error:
                return build_brief(session, None, str(error), error.hint)
    finally:
        engine.dispose()


def found_by(database_url: str, cwd: str) -> tuple[str, str]:
    engine = make_engine(database_url)
    try:
        with make_session_factory(engine)() as session:
            project, how = resolve_project(session, None, cwd)
            return project.name, how
    finally:
        engine.dispose()


@linux_folders
async def test_a_folder_chosen_through_the_flatpak_picker_still_matches(
    database_url: str, logs
) -> None:
    async with app_client(database_url) as client:
        pid = await seed_game(client, PORTAL)
        before = brief_from(database_url, f"{REAL}/game")
        assert "PROJECT: Ember Road" not in before  # what happened: global rules only
        # Agents work in the real folder, one level deeper, as a Godot project often sits.
        logs["session"](f"{REAL}/game")
        logs["session"](REAL)
        synced = (await client.get("/api/agent-folders")).json()
        assert synced["created"] == [], "no second project for the same folder"
        row = next(r for r in synced["folders"] if r["folder"] == REAL)
        assert row["status"] == "linked" and row["project_id"] == pid
        # The project keeps the folder the app opens it through.
        assert (await client.get(f"/api/projects/{pid}")).json()["root_path"] == PORTAL

    for cwd in (REAL, f"{REAL}/game", f"{REAL}/game/scenes/battle"):
        brief = brief_from(database_url, cwd)
        assert "PROJECT: Ember Road" in brief, cwd
        assert "Check sprites zoomed in before showing them" in brief
        assert "No stat may drop when a unit evolves" in brief
        assert "UNFINISHED: EMB-001 Rebalance the second island" in brief
        assert "Run the balance sim" in brief


@linux_folders
async def test_a_linked_folder_matches_and_linking_never_drops_the_projects_own(
    database_url: str, logs
) -> None:
    async with app_client(database_url) as client:
        pid = await seed_game(client, "/home/me/Projects/ember-road")
        await post(client, "/api/projects", {"name": "Ember Road Trailer"})
        logs["session"]("/home/me/Desktop/Ember Road Trailer copy")
        synced = (await client.get("/api/agent-folders")).json()
        waiting = synced["suggested"]
        assert waiting == ["/home/me/Desktop/Ember Road Trailer copy"]
        assert "waiting for the person to confirm" in brief_from(database_url, waiting[0])
        # The person says it is Ember Road's, although Ember Road already has a folder.
        linked = await client.post(
            "/api/agent-folders/decide",
            json={"folder": waiting[0], "action": "link", "project_id": pid},
        )
        assert linked.status_code == 200, linked.text
        project = (await client.get(f"/api/projects/{pid}")).json()
        assert project["root_path"] == "/home/me/Projects/ember-road"

    assert found_by(database_url, f"{waiting[0]}/src") == ("Ember Road", "working directory")
    assert found_by(database_url, "/home/me/Projects/ember-road/src") == (
        "Ember Road",
        "working directory",
    )


@linux_folders
async def test_ignored_and_temporary_folders_say_why_nothing_matched(
    database_url: str, logs
) -> None:
    async with app_client(database_url) as client:
        await seed_game(client, "/home/me/Projects/ember-road")
        await post(client, "/api/projects", {"name": "Ember Sketches"})
        scratch = "/home/me/Desktop/Ember Sketches old"
        logs["session"](scratch)
        assert (await client.get("/api/agent-folders")).json()["suggested"] == [scratch]
        ignored = await client.post(
            "/api/agent-folders/decide", json={"folder": scratch, "action": "ignore"}
        )
        assert ignored.status_code == 200
    assert "chose to ignore this folder" in brief_from(database_url, f"{scratch}/src")
    assert "temporary, system or home folder" in brief_from(database_url, "/tmp/claude-1000/x")
    assert "temporary, system or home folder" in brief_from(database_url, "/home/me")


async def test_a_clone_elsewhere_matches_by_its_git_remote(
    database_url: str, tmp_path: Path
) -> None:
    def repo(folder: Path, url: str) -> Path:
        (folder / ".git").mkdir(parents=True)
        (folder / ".git" / "config").write_text(
            "[core]\n\tbare = false\n"
            '[remote "upstream"]\n\turl = https://github.com/someone-else/fork.git\n'
            f'[remote "origin"]\n\turl = {url}\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n'
        )
        return folder

    main = repo(tmp_path / "ember-road", "https://github.com/Starfield/Ember-Road.git")
    clone = repo(tmp_path / "laptop-copy" / "ember", "git@github.com:starfield/ember-road")
    other = repo(tmp_path / "unrelated", "https://github.com/starfield/notes.git")
    # A worktree kept outside the repository: its ".git" is a file pointing back.
    worktree_git = main / ".git" / "worktrees" / "wt"
    worktree_git.mkdir(parents=True)
    (worktree_git / "commondir").write_text("../..\n")
    worktree = tmp_path / "ember-wt"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {worktree_git}\n")
    (clone / "src").mkdir()

    async with app_client(database_url) as client:
        await seed_game(client, str(main))
        await post(client, "/api/projects", {"name": "Notes", "root_path": str(other)})

    assert found_by(database_url, str(main / "x")) == ("Ember Road", "working directory")
    assert found_by(database_url, str(clone / "src")) == ("Ember Road", "git remote")
    assert found_by(database_url, str(worktree)) == ("Ember Road", "git remote")
    assert "PROJECT: Ember Road" in brief_from(database_url, str(clone))

    # Two projects in one repository: never a guess.
    async with app_client(database_url) as client:
        await post(client, "/api/projects", {"name": "Ember Road Docs", "root_path": str(main)})
    assert "Candidates" in brief_from(database_url, str(clone))


def test_remote_spellings_name_one_repository(tmp_path: Path) -> None:
    same = {
        normalize_remote(url)
        for url in (
            "https://github.com/Starfield/Ember-Road.git",
            "https://user@github.com/starfield/ember-road/",
            "git@github.com:starfield/ember-road.git",
            "ssh://git@github.com:22/Starfield/Ember-Road",
        )
    }
    assert same == {"github.com/starfield/ember-road"}
    assert normalize_remote("") is None
    assert repository_remote(str(tmp_path)) is None  # not a repository
    assert repository_remote("relative/folder") is None


async def test_a_session_only_folder_is_never_saved_as_a_projects_folder(
    client: AsyncClient,
) -> None:
    refused = await client.post(
        "/api/projects",
        json={"name": "Ember Road", "root_path": "/sessions/brave-owl/mnt/Ember Road"},
    )
    assert refused.status_code == 422
    if sys.platform == "win32":
        return  # not an absolute path on Windows, so it is refused before the folder check
    assert "only exists while one session runs" in refused.text
    # A document portal path is kept: it is how a Flatpak install opens the folder.
    kept = await client.post("/api/projects", json={"name": "Ember Road", "root_path": PORTAL})
    assert kept.status_code == 201

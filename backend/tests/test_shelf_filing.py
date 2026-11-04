"""New records file themselves on the shelf their work belongs to, in a realistic setup: a
shared knowledge tree with game shelves deeper than the software ones, two projects with
history on it (rules, memories, a checkpoint, a half-done task), and an agent picking up the
half-done task and writing new tasks and notes, the way a real session does.

The cases come from records that landed on game shelves before: a code of conduct "needs" a
contact (idle game "needs"), ranking context pack "records" (sound "recordings"), a settings
panel in a desktop app (game menus)."""

from pathlib import Path

import pytest
from httpx import AsyncClient

from app.db.session import make_engine, make_session_factory
from app.models.graph import Shelf
from app.services.health import HealthService
from app.services.shelves import ShelfService
from tests.conftest import app_client
from tests.test_mcp import agent, call

pytestmark = pytest.mark.anyio

GAME = "Knowledge > Game development"
MECHANICS = f"{GAME} > Game design > Game mechanics"
SOFTWARE = "Knowledge > Software engineering"
AGENTS = "Knowledge > AI agents"
TREE = {
    f"{MECHANICS} > Combat": ["combat", "enemy", "boss", "dodge"],
    f"{MECHANICS} > Idle loops": ["idle", "needs", "offline", "incremental"],
    f"{MECHANICS} > Economy and items": ["shop", "price", "items", "currency"],
    f"{GAME} > Game UI": ["ui", "hud", "menu"],
    f"{GAME} > Game UI > Menus and screens": ["settings", "panel", "menu", "screen"],
    f"{GAME} > Game audio > Sound effects": ["sfx", "recording", "cue"],
    f"{SOFTWARE} > Frontend > UI/UX": ["ui", "ux", "layout", "usability"],
    f"{SOFTWARE} > Build and release": ["release", "build", "packaging", "installer"],
    f"{SOFTWARE} > Version control": ["git", "commit", "push", "branch"],
    f"{SOFTWARE} > Open source": ["license", "contributors", "code of conduct"],
    f"{AGENTS} > Memory and retrieval": ["memory", "retrieval", "context pack", "ranking"],
}


async def post(client: AsyncClient, url: str, **body: object) -> dict:
    response = await client.post(url, json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()


async def seed(client: AsyncClient, tmp_path: Path) -> dict:
    notebook = await post(
        client, "/api/projects", name="Notebook", root_path=str(tmp_path / "notebook")
    )
    camp = await post(client, "/api/projects", name="Ember Camp", root_path=str(tmp_path / "camp"))
    await post(
        client,
        "/api/projects/global/memory",
        type="rule",
        title="Ask before adding dependencies",
        content="Show the package and why before installing anything new.",
        importance="high",
    )
    await post(
        client,
        f"/api/projects/{notebook['id']}/memory",
        type="rule",
        title="Keep everything local",
        content="No cloud services or remote models in the app.",
        importance="high",
    )
    notes = {
        "notebook": [
            ("Memory and retrieval", "decision", "Packs rank exact matches first"),
            ("Memory and retrieval", "fact", "Search index is SQLite FTS5"),
            ("Memory and retrieval", "warning", "Graph walk can flood packs with old notes"),
            ("Build and release", "fact", "Installer is built by the release workflow"),
            ("Build and release", "decision", "Releases are cut from main only"),
            ("Version control", "note", "Commit titles say what changed"),
        ],
        "camp": [
            ("Combat", "decision", "Bosses telegraph attacks for half a second"),
            ("Combat", "fact", "Dodge has twelve frames of immunity"),
            ("Idle loops", "decision", "Camp needs decay while offline"),
            ("Economy and items", "fact", "Shop prices scale with camp level"),
            ("Menus and screens", "note", "Settings screen opens from the camp fire"),
        ],
    }
    task = await post(
        client,
        f"/api/projects/{notebook['id']}/tasks",
        title="Rank pack results by exact term match",
        prefix="NB",
        next_action="Wire the exact-match score into the pack ranking",
        acceptance_criteria=["Exact matches rank first", "Old packs still load"],
    )
    await client.post(f"/api/projects/{notebook['id']}/tasks/{task['id']}/start")
    await post(
        client,
        f"/api/projects/{notebook['id']}/checkpoints",
        task_id=task["id"],
        title="Exact-match score half done",
        completed_work="Score computed per record",
        remaining_work="Use it in the ranking and test old packs",
    )
    out = {"notebook": notebook["id"], "camp": camp["id"], "task": task["human_id"], "notes": {}}
    async with agent(f"sqlite:///{tmp_path / 'project-brain.db'}") as session:
        for path, words in TREE.items():
            failed, _ = await call(
                session,
                "brain_update_shelf",
                shelf=path,
                shared=True,
                keywords=words,
                project="global",
            )
            assert not failed
        for project, rows in notes.items():
            for shelf, kind, title in rows:
                made = await post(
                    client, f"/api/projects/{out[project]}/memory", type=kind, title=title
                )
                failed, _ = await call(
                    session,
                    "brain_update_shelf",
                    shelf=shelf,
                    shared=True,
                    add=[made["human_id"]],
                    project=out[project],
                )
                assert not failed
    return out


async def test_new_records_file_where_their_work_belongs(database_url: str, tmp_path: Path) -> None:
    async with app_client(database_url) as client:
        ids = await seed(client, tmp_path)
    nb, camp = ids["notebook"], ids["camp"]
    async with agent(database_url) as session:
        # The agent picks up the half-done task, which makes it this session's task.
        failed, _ = await call(session, "brain_context_pack", task=ids["task"], project=nb)
        assert not failed

        async def task(title: str, project: str, description: str = "") -> str | None:
            failed, made = await call(
                session, "brain_create_task", title=title, description=description, project=project
            )
            assert not failed, made
            return made.get("shelf")

        async def note(title: str, project: str, content: str = "") -> str | None:
            failed, made = await call(
                session,
                "brain_create_memory",
                type="note",
                title=title,
                content=content,
                project=project,
            )
            assert not failed, made
            return made.get("shelf")

        # Words that also name game shelves no longer pull software work onto them.
        assert (
            await task(
                "Sort context pack records by exact term match",
                nb,
                "Records with the exact words first, then the graph walk.",
            )
            == f"shared: {AGENTS} > Memory and retrieval"
        )
        assert (
            await task("Add a code of conduct", nb, "Needs a public contact address.")
            == f"shared: {SOFTWARE} > Open source"
        )
        assert await task("Push the release branch", nb) in {
            f"shared: {SOFTWARE} > Version control",
            f"shared: {SOFTWARE} > Build and release",
        }
        settings = await note("Settings panel for the update check", nb)
        assert settings is None or GAME not in settings
        # One stray word on a branch the project never used files nothing.
        assert await task("Write down what the next steps need", nb) is None

        # Game work still lands on the game shelves.
        assert (
            await task("Boss enemy wind-up timing", camp, "The boss telegraphs before each attack.")
            == f"shared: {MECHANICS} > Combat"
        )
        assert (
            await note("Idle needs decay offline", camp, "Needs drop by a tenth per hour offline.")
            == f"shared: {MECHANICS} > Idle loops"
        )
        assert (
            await task("Settings menu screen", camp)
            == f"shared: {GAME} > Game UI > Menus and screens"
        )


async def test_a_new_project_files_only_on_strong_words(database_url: str, tmp_path: Path) -> None:
    async with app_client(database_url) as client:
        await seed(client, tmp_path)
        new = (await post(client, "/api/projects", name="Garden Log"))["id"]
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        shelves = ShelfService(session)
        # Nothing filed yet: one plain word is not enough, a shelf's phrase or two words are.
        assert shelves.suggest(new, "What the tomatoes need in summer") is None
        best = shelves.suggest(new, "Write the code of conduct")
        assert best is not None and best.name == "Open source"
        best = shelves.suggest(new, "Build the installer")
        assert best is not None and best.name == "Build and release"


async def test_everyday_words_never_file_and_leave_the_keywords(
    database_url: str, tmp_path: Path
) -> None:
    """Keywords a shelf picked up from the words of the work ("after", "need") woke game
    shelves for software tasks. They no longer count, and the daily upkeep drops them."""
    async with app_client(database_url) as client:
        ids = await seed(client, tmp_path)
        rewards = (await client.get("/api/projects/global/shelves/Economy and items")).json()
        await client.patch(
            f"/api/projects/global/shelves/{rewards['id']}",
            json={
                "keywords": ["shop", "price", "items", "currency", "after", "target", "ask before"]
            },
        )
    factory = make_session_factory(make_engine(database_url))
    with factory() as session:
        shelves = ShelfService(session)
        # A Notebook task: only "after" names a game shelf, and an everyday word names nothing.
        best = shelves.suggest(ids["notebook"], "Ship the branch ruleset after the review")
        assert best is None or GAME not in best.path
        # Game work still finds the shelf by its real words.
        best = shelves.suggest(ids["camp"], "Shop price for the camp axe")
        assert best is not None and best.name == "Economy and items"

        organized = HealthService(session).organize(ids["notebook"])
        assert organized["dropped_word"] == 2  # "after" here, "needs" on Idle loops
        keywords = session.get(Shelf, rewards["id"]).keywords.split(",")
        assert "after" not in keywords and "target" in keywords
        assert "ask before" in keywords  # a phrase of everyday words still names its topic

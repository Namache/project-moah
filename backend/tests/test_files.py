import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


@pytest.fixture(autouse=True)
def outside_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests behave the same whether or not they run inside a Flatpak (the SDK test run does)."""
    monkeypatch.setattr("app.services.git.in_sandbox", lambda: False)


def git(repo: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_AUTHOR_NAME": "Ada",
        "GIT_AUTHOR_EMAIL": "ada@example.test",
        "GIT_COMMITTER_NAME": "Ada",
        "GIT_COMMITTER_EMAIL": "ada@example.test",
    }
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)


def make_repo(root: Path) -> Path:
    (root / "systems/camp").mkdir(parents=True)
    (root / "systems/camp/camp_manager.gd").write_text("extends Node\n")
    (root / "README.md").write_text("# Game\n")
    (root / ".gitignore").write_text("ignored.txt\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "Initial import")
    return root


async def project(client: AsyncClient, name: str, root: Path | None = None) -> str:
    body: dict = {"name": name}
    if root is not None:
        body["root_path"] = str(root)
    return (await client.post("/api/projects", json=body)).json()["id"]


async def test_file_notes_paths_symbols_links_and_isolation(client: AsyncClient) -> None:
    a, b = await project(client, "A"), await project(client, "B")
    task_a = (await client.post(f"/api/projects/{a}/tasks", json={"title": "Camp"})).json()
    task_b = (await client.post(f"/api/projects/{b}/tasks", json={"title": "Other"})).json()
    mem = (
        await client.post(
            f"/api/projects/{a}/memory", json={"type": "rule", "title": "Use signals"}
        )
    ).json()
    base = f"/api/projects/{a}/files"
    for bad in ("../secret", "/etc/passwd", "a/../../b", "C:/x", "a\\b", ""):
        assert (await client.post(base, json={"path": bad})).status_code == 422, bad

    created = await client.post(
        base,
        json={
            "path": "./systems//camp/camp_manager.gd",
            "purpose": "Owns camp capacity",
            "symbols": [
                {"name": "CampManager", "kind": "class"},
                {"name": "CampManager", "kind": "class"},
                {"name": "get_capacity()", "kind": "method"},
            ],
            "task_ids": [task_a["human_id"]],
            "memory_ids": [mem["human_id"]],
        },
    )
    assert created.status_code == 201, created.text
    file = created.json()
    assert file["path"] == "systems/camp/camp_manager.gd" and file["language"] == "gdscript"
    assert [s["name"] for s in file["symbols"]] == ["CampManager", "get_capacity()"]
    assert [t["human_id"] for t in file["tasks"]] == [task_a["human_id"]]
    assert [m["human_id"] for m in file["memories"]] == ["RULE-001"]
    assert (
        await client.post(base, json={"path": "systems/camp/camp_manager.gd"})
    ).status_code == 409

    by_path = (
        await client.get(f"{base}/by-path", params={"path": "systems/camp/camp_manager.gd"})
    ).json()
    assert by_path["id"] == file["id"]
    patched = (
        await client.patch(
            f"{base}/{file['id']}", json={"summary": "Capacity state", "task_ids": []}
        )
    ).json()
    assert (
        patched["tasks"] == []
        and patched["summary"] == "Capacity state"
        and len(patched["symbols"]) == 2
    )
    assert (await client.patch(f"{base}/{file['id']}", json={})).status_code == 422
    assert (
        await client.patch(f"{base}/{file['id']}", json={"task_ids": [task_b["id"]]})
    ).status_code == 404

    # Another project cannot see or reach these notes, and search stays inside each project.
    assert (await client.get(f"/api/projects/{b}/files/{file['id']}")).status_code == 404
    assert (await client.get(f"/api/projects/{b}/files")).json() == []
    found = (
        await client.get(
            f"/api/projects/{a}/search", params={"q": "capacity", "entity_type": "file"}
        )
    ).json()["items"]
    assert [h["title"] for h in found] == ["systems/camp/camp_manager.gd"]
    assert (await client.get(f"/api/projects/{b}/search", params={"q": "capacity"})).json()[
        "items"
    ] == []
    assert (await client.get(f"/api/projects/{a}/files", params={"q": "camp_manager"})).json()[0][
        "id"
    ] == file["id"]

    assert (await client.delete(f"{base}/{file['id']}")).status_code == 204
    assert (await client.get(f"{base}/{file['id']}")).status_code == 404
    assert (
        await client.get(
            f"/api/projects/{a}/search", params={"q": "capacity", "entity_type": "file"}
        )
    ).json()["items"] == []


@needs_git
async def test_git_status_tree_staleness_and_safe_deletion(
    client: AsyncClient, tmp_path: Path
) -> None:
    repo = make_repo(tmp_path / "repo")
    pid = await project(client, "Trailhead", repo)
    base = f"/api/projects/{pid}"

    status = (await client.get(f"{base}/git")).json()
    assert (status["state"], status["branch"], status["clean"]) == ("ok", "main", True)
    assert status["head_subject"] == "Initial import"

    (repo / "README.md").write_text("# Changed\n")
    (repo / "new_file.gd").write_text("x\n")
    (repo / "ignored.txt").write_text("nope\n")
    status = (await client.get(f"{base}/git")).json()
    assert status["clean"] is False
    assert {(c["path"], c["status"]) for c in status["changed"]} == {
        ("README.md", "modified"),
        ("new_file.gd", "untracked"),
    }

    note = (
        await client.post(f"{base}/files", json={"path": "README.md", "purpose": "Docs"})
    ).json()
    assert note["language"] == "markdown" and note["last_seen_hash"] and note["stale"] is False
    tree = (await client.get(f"{base}/files/tree")).json()
    entries = {e["path"]: e for e in tree["entries"]}
    assert tree["source"] == "git" and "ignored.txt" not in entries
    assert entries["README.md"]["has_notes"] and entries["README.md"]["changed"] == "modified"
    assert (
        entries["new_file.gd"]["changed"] == "untracked" and not entries["new_file.gd"]["has_notes"]
    )

    (repo / "README.md").write_text("# Changed again\n")
    assert (await client.get(f"{base}/files/{note['id']}")).json()["stale"] is True
    assert {e["path"]: e for e in (await client.get(f"{base}/files/tree")).json()["entries"]}[
        "README.md"
    ]["stale"] is True
    assert (await client.post(f"{base}/files/{note['id']}/reviewed")).json()["stale"] is False

    # Removing the notes never touches the real file.
    assert (await client.delete(f"{base}/files/{note['id']}")).status_code == 204
    assert (repo / "README.md").read_text() == "# Changed again\n"
    # And nothing in Project Moah could have changed the repository's history.
    log = subprocess.run(
        ["git", "-C", str(repo), "log", "--oneline"], capture_output=True, text=True, check=True
    ).stdout
    assert log.count("\n") == 1


@needs_git
async def test_commits_suggestions_confirmation_and_history_survives(
    client: AsyncClient, tmp_path: Path
) -> None:
    repo = make_repo(tmp_path / "repo")
    pid = await project(client, "Trailhead", repo)
    other = await project(client, "Other")
    base = f"/api/projects/{pid}"
    task = (await client.post(f"{base}/tasks", json={"title": "Camp", "prefix": "CAMP"})).json()
    (repo / "systems/camp/camp_manager.gd").write_text("extends Node\nfunc capacity(): pass\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "CAMP-001 add capacity validation; also OTHER-9")

    listing = (await client.get(f"{base}/git/commits")).json()
    latest = listing["commits"][0]
    assert latest["subject"].startswith("CAMP-001") and len(latest["short_sha"]) == 8
    # A task ID in the message is only a suggestion until a person confirms it.
    assert [(t["task"]["human_id"], t["status"]) for t in latest["tasks"]] == [
        ("CAMP-001", "suggested")
    ]
    assert (await client.get(f"{base}/git/commits", params={"task": "CAMP-001"})).json()[
        "commits"
    ] == []

    linked = (
        await client.post(f"{base}/git/commits/{latest['sha']}/tasks", json={"task": "CAMP-001"})
    ).json()
    assert [(t["task"]["human_id"], t["status"]) for t in linked["tasks"]] == [
        ("CAMP-001", "confirmed")
    ]
    assert linked["files"] == ["systems/camp/camp_manager.gd"]
    for_task = (await client.get(f"{base}/git/commits", params={"task": task["id"]})).json()[
        "commits"
    ]
    assert [c["sha"] for c in for_task] == [latest["sha"]]
    events = (await client.get(f"{base}/activity")).json()
    assert "GIT_COMMIT_DETECTED" in {e["event_type"] for e in events}
    assert (
        await client.post(f"{base}/git/commits/zzzz/tasks", json={"task": "CAMP-001"})
    ).status_code == 422
    assert (
        await client.post(
            f"/api/projects/{other}/git/commits/{latest['sha']}/tasks", json={"task": "CAMP-001"}
        )
    ).status_code == 404

    # The repository goes away. Stored links remain, and every screen still answers.
    shutil.rmtree(repo, onexc=lambda remove, path, _: (os.chmod(path, stat.S_IWRITE), remove(path)))
    gone = (await client.get(f"{base}/git/commits")).json()
    assert gone["git"]["state"] == "path_missing"
    assert [(c["short_sha"], c["in_repository"]) for c in gone["commits"]] == [
        (latest["short_sha"], False)
    ]
    assert (await client.get(f"{base}/files/tree")).json()["source"] == "notes"
    assert (
        await client.delete(f"{base}/git/commits/{latest['sha']}/tasks/CAMP-001")
    ).status_code == 204
    assert (
        await client.delete(f"{base}/git/commits/{latest['sha']}/tasks/CAMP-001")
    ).status_code == 404


async def test_git_problems_are_reported_not_raised(
    client: AsyncClient, tmp_path: Path, monkeypatch
) -> None:
    none = await project(client, "NoRepo")
    assert (await client.get(f"/api/projects/{none}/git")).json()["state"] == "no_path"
    plain = tmp_path / "plain"
    (plain / "src").mkdir(parents=True)
    (plain / "src/app.py").write_text("print(1)\n")
    (plain / "node_modules").mkdir()
    (plain / "node_modules/skip.js").write_text("x")
    pid = await project(client, "Plain", plain)
    twin = await project(client, "Twin", plain)
    status = (await client.get(f"/api/projects/{pid}/git")).json()
    assert status["state"] in ("not_repo", "git_missing") and status["message"]
    assert "Twin" in status["warnings"][0]  # two projects, one folder
    assert (await client.get(f"/api/projects/{twin}/git")).json()["warnings"][0].endswith("Plain.")
    tree = (await client.get(f"/api/projects/{pid}/files/tree")).json()
    assert tree["source"] == "folder" and [e["path"] for e in tree["entries"]] == ["src/app.py"]

    monkeypatch.setattr("app.services.git.shutil.which", lambda _name: None)
    assert (await client.get(f"/api/projects/{pid}/git")).json()["state"] == "git_missing"
    assert (await client.get(f"/api/projects/{pid}/git/commits")).json()["commits"] == []
    assert (await client.get(f"/api/projects/{pid}/files/tree")).status_code == 200
    gone = await project(client, "Gone", tmp_path / "missing")
    assert (await client.get(f"/api/projects/{gone}/git")).json()["state"] == "path_missing"


async def test_file_hash_never_follows_a_link_out_of_the_repository(
    client: AsyncClient, tmp_path: Path
) -> None:
    repo, outside = tmp_path / "repo", tmp_path / "outside.txt"
    repo.mkdir()
    outside.write_text("secret")
    (repo / "link.txt").symlink_to(outside)
    pid = await project(client, "Linked", repo)
    note = (await client.post(f"/api/projects/{pid}/files", json={"path": "link.txt"})).json()
    assert note["last_seen_hash"] is None and note["stale"] is None


async def test_context_pack_lists_linked_files_and_flags_changed_ones(
    client: AsyncClient, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "camp.gd").write_text("a")
    (repo / "save.gd").write_text("b")
    pid = await project(client, "Trailhead", repo)
    base = f"/api/projects/{pid}"
    task = (await client.post(f"{base}/tasks", json={"title": "Camp capacity"})).json()
    other = await project(client, "Starling")
    await client.post(
        f"/api/projects/{other}/files", json={"path": "elsewhere.gd", "purpose": "Not ours"}
    )
    await client.post(
        f"{base}/files",
        json={"path": "camp.gd", "purpose": "Owns capacity", "task_ids": [task["id"]]},
    )
    await client.post(f"{base}/files", json={"path": "save.gd", "purpose": "Unlinked"})
    pack = (await client.get(f"{base}/context", params={"task": task["human_id"]})).json()
    assert "RELEVANT FILES\ncamp.gd\n  Owns capacity" in pack["text"]
    assert "save.gd" not in pack["text"] and "elsewhere.gd" not in pack["text"]
    assert {i["title"] for i in pack["items"] if i["section"] == "files"} == {"camp.gd"}


async def test_a_folder_the_sandbox_cannot_see_says_so(
    client: AsyncClient, tmp_path: Path, monkeypatch
) -> None:
    pid = await project(client, "Containerised", tmp_path / "not-shared")
    outside = (await client.get(f"/api/projects/{pid}/git")).json()
    assert outside["state"] == "path_missing"  # an ordinary missing folder
    monkeypatch.setattr("app.services.git.in_sandbox", lambda: True)
    inside = (await client.get(f"/api/projects/{pid}/git")).json()
    assert (
        inside["state"] == "not_shared"
        and "share" in inside["message"]
        and "Choose folder" in inside["message"]
    )
    assert (await client.get(f"/api/projects/{pid}/files/tree")).json()["source"] == "notes"
    assert (await client.get(f"/api/projects/{pid}/git/commits")).json()["commits"] == []


async def test_files_without_a_dot_or_slash_are_found_by_path(client: AsyncClient) -> None:
    a = await project(client, "Paths")
    base = f"/api/projects/{a}/files"
    created = await client.post(base, json={"path": "Makefile", "purpose": "Build"})
    assert created.status_code == 201
    found = await client.get(f"{base}/by-path", params={"path": "Makefile"})
    assert found.status_code == 200 and found.json()["purpose"] == "Build"
    by_id = await client.get(f"{base}/{created.json()['id']}")
    assert by_id.status_code == 200


@needs_git
async def test_git_status_in_a_project_inside_a_repository_subfolder(
    client: AsyncClient, tmp_path: Path
) -> None:
    repo = make_repo(tmp_path / "repo")
    (repo / "systems/camp/camp_manager.gd").write_text("extends Node2D\n")
    (repo / "README.md").write_text("# Changed outside the project\n")
    a = await project(client, "Camp", repo / "systems")
    status = (await client.get(f"/api/projects/{a}/git")).json()
    assert [c["path"] for c in status["changed"]] == ["camp/camp_manager.gd"]


def test_an_unstaged_rename_is_one_change() -> None:
    from app.services.git import GitService

    changed = GitService._parse_status(" R new.txt\x00old.txt\x00 M other.txt\x00")
    assert [c.path for c in changed] == ["new.txt", "other.txt"]


@needs_git
async def test_commit_links_reject_wildcards(client: AsyncClient, tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    a = await project(client, "Wild", repo)
    await client.post(f"/api/projects/{a}/tasks", json={"title": "T", "prefix": "CAMP"})
    base = f"/api/projects/{a}"
    sha = (await client.get(f"{base}/git/commits")).json()["commits"][0]["sha"]
    assert (
        await client.post(f"{base}/git/commits/{sha}/tasks", json={"task": "CAMP-001"})
    ).status_code == 201
    for bad in ("%25", "_______"):
        response = await client.post(f"{base}/git/commits/{bad}/tasks", json={"task": "CAMP-001"})
        assert response.status_code in (404, 409, 422)

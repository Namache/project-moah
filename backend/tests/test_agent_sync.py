"""Sync from agents: projects from the folders Claude Code and Codex sessions start in."""

import json
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest
from httpx import AsyncClient

from app.services.agent_sync import project_folder
from app.services.usage import normalize_folder

pytestmark = pytest.mark.anyio
# These describe Linux folders (/home, /var/home on Fedora Atomic, /tmp), which a Windows
# project cannot have; test_windows_folders_count_as_projects covers Windows.
linux_folders = pytest.mark.skipif(sys.platform == "win32", reason="Linux folder layout")


@pytest.fixture
def logs(tmp_path: Path, monkeypatch) -> dict:
    claude, codex = tmp_path / "claude", tmp_path / "codex"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    monkeypatch.setenv("CODEX_HOME", str(codex))
    monkeypatch.setenv("HOME", "/home/me")
    count = {"n": 0}

    def session(agent: str, cwd: str) -> None:
        count["n"] += 1
        if agent == "claude":
            path = claude / "projects" / cwd.replace("/", "-") / f"s{count['n']}.jsonl"
            line = {
                "type": "user",
                "cwd": cwd,
                "timestamp": "2026-10-11T00:00:00Z",
                "message": {"content": "SECRET"},
            }
        else:
            path = codex / "sessions" / "2026" / "10" / "11" / f"rollout-{count['n']}.jsonl"
            line = {
                "type": "session_meta",
                "timestamp": "2026-10-11T00:00:00Z",
                "payload": {"cwd": cwd},
            }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"type": "summary"}) + "\n" + json.dumps(line) + "\n")

    return {"session": session}


def test_which_folders_count_as_projects(monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: PurePosixPath("/home/me")))
    assert project_folder("/home/me/Desktop/Game") == "/home/me/Desktop/Game"
    assert (
        project_folder("/home/me/Desktop/Game/.claude/worktrees/brave-x") == "/home/me/Desktop/Game"
    )
    assert project_folder("/tmp/claude-1000/x/scratchpad/ui1") is None
    assert project_folder("/home/me/Documents/Codex/2026-10-06/create-a-mod") is None
    assert project_folder("/home/me") is None
    assert project_folder("/home/me/.codex/worktrees/abc") is None


def test_windows_folders_count_as_projects(monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: PureWindowsPath(r"C:\Users\me")))

    def folder(path: str) -> str | None:
        return project_folder(normalize_folder(path))

    assert folder(r"C:\Users\me\Desktop\Game") == "C:/Users/me/Desktop/Game"
    assert (
        folder(r"c:\Users\me\Desktop\Game\.claude\worktrees\brave-x") == "C:/Users/me/Desktop/Game"
    )
    assert folder(r"D:\Projects\Game") == "D:/Projects/Game"
    assert folder(r"C:\Users\me") is None
    assert folder("C:\\") is None
    assert folder(r"C:\Users\me\AppData\Local\Temp\scratch") is None


@linux_folders
async def test_sync_creates_projects_and_never_guesses_a_match(client: AsyncClient, logs) -> None:
    climb = (await client.post("/api/projects", json={"name": "Trailhead"})).json()
    await client.post(
        "/api/projects", json={"name": "Brain", "root_path": "/home/me/Desktop/brain"}
    )
    for agent, cwd in [
        ("claude", "/home/me/Desktop/Protoype"),
        ("codex", "/var/home/me/Desktop/Protoype"),  # the same folder, spelled the host's way
        ("claude", "/home/me/Desktop/Protoype/src"),  # inside it: counted there
        ("claude", "/home/me/Desktop/Trailhead - Idle Game"),
        ("codex", "/home/me/Desktop/brain/backend"),  # already a project's folder
        ("codex", "/tmp/scratch/ui1"),
        ("codex", "/home/me/Documents/Codex/2026-10-08/one-off"),
    ]:
        logs["session"](agent, cwd)

    first = (await client.get("/api/agent-folders")).json()
    assert first["created"] == ["Protoype"]
    assert first["suggested"] == ["/home/me/Desktop/Trailhead - Idle Game"]
    assert "SECRET" not in json.dumps(first)
    rows = {row["folder"]: row for row in first["folders"]}
    assert set(rows) == {
        "/home/me/Desktop/Protoype",
        "/home/me/Desktop/Trailhead - Idle Game",
        "/home/me/Desktop/brain",
    }
    assert (
        rows["/home/me/Desktop/Protoype"]["claude_sessions"] == 2
        and rows["/home/me/Desktop/Protoype"]["codex_sessions"] == 1
    )
    assert rows["/home/me/Desktop/brain"]["status"] == "linked"
    suggestion = rows["/home/me/Desktop/Trailhead - Idle Game"]
    assert suggestion["status"] == "suggested" and suggestion["project_id"] == climb["id"]
    names = sorted(p["name"] for p in (await client.get("/api/projects")).json())
    assert names == ["Brain", "Protoype", "Trailhead"]

    # Running again changes nothing.
    again = (await client.get("/api/agent-folders")).json()
    assert again["created"] == [] and again["suggested"] == []

    # The person confirms the match: Trailhead gets the folder.
    linked = await client.post(
        "/api/agent-folders/decide", json={"folder": suggestion["folder"], "action": "link"}
    )
    assert linked.status_code == 200, linked.text
    assert (await client.get(f"/api/projects/{climb['id']}")).json()["root_path"] == suggestion[
        "folder"
    ]


@linux_folders
async def test_ignored_and_archived_folders_stay_away(client: AsyncClient, logs) -> None:
    logs["session"]("claude", "/home/me/Desktop/Noise")
    logs["session"]("codex", "/home/me/Desktop/Old")
    await client.get("/api/agent-folders")
    projects = {p["name"]: p for p in (await client.get("/api/projects")).json()}
    await client.post(f"/api/projects/{projects['Old']['id']}/archive")
    ignored = await client.post(
        "/api/agent-folders/decide", json={"folder": "/home/me/Desktop/Noise", "action": "ignore"}
    )
    assert ignored.status_code == 200
    logs["session"]("claude", "/home/me/Desktop/Old")
    logs["session"]("claude", "/home/me/Desktop/Noise/deeper")
    after = (await client.get("/api/agent-folders")).json()
    assert after["created"] == []
    assert [p["name"] for p in (await client.get("/api/projects")).json()] == [
        "Noise"
    ]  # existing, not recreated


@linux_folders
async def test_a_suggestion_can_become_its_own_project(client: AsyncClient, logs) -> None:
    await client.post("/api/projects", json={"name": "Trailhead"})
    logs["session"]("claude", "/home/me/Desktop/Trailhead Trailer")
    folder = "/home/me/Desktop/Trailhead Trailer"
    assert (await client.get("/api/agent-folders")).json()["suggested"] == [folder]
    made = await client.post(
        "/api/agent-folders/decide", json={"folder": folder, "action": "create"}
    )
    assert made.status_code == 200
    names = sorted(p["name"] for p in (await client.get("/api/projects")).json())
    assert names == ["Trailhead", "Trailhead Trailer"]
    bad = await client.post(
        "/api/agent-folders/decide", json={"folder": "/nope", "action": "ignore"}
    )
    assert bad.status_code == 404

import sqlite3
from pathlib import Path

import pytest
from httpx import AsyncClient

from tests.conftest import app_client

pytestmark = pytest.mark.anyio


async def test_diagnostics_report_health_without_leaking_content(
    client: AsyncClient, database_url: str, monkeypatch
) -> None:
    monkeypatch.setenv("PROJECT_BRAIN_DATABASE_URL", database_url)
    pid = (await client.post("/api/projects", json={"name": "Secret Project"})).json()["id"]
    await client.post(f"/api/projects/{pid}/tasks", json={"title": "Top secret plan"})
    report = (await client.get("/api/system/diagnostics")).json()
    assert (
        report["database"]["integrity"] == "ok" and report["database"]["foreign_key_problems"] == 0
    )
    assert (
        report["database"]["search_index_ready"] is True
        and report["database"]["migration"] == "0015_images"
    )
    assert report["counts"]["projects"] == 1 and report["counts"]["tasks"] == 1
    assert (
        report["database"]["path"].endswith("project-brain.db")
        and report["database"]["size_bytes"] > 0
    )
    assert "Secret" not in str(report) and "secret plan" not in str(report)  # counts, never content


async def test_export_is_a_consistent_copy_that_opens_on_its_own(
    client: AsyncClient, database_url: str, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PROJECT_BRAIN_DATABASE_URL", database_url)
    pid = (await client.post("/api/projects", json={"name": "Trailhead"})).json()["id"]
    await client.post(
        f"/api/projects/{pid}/memory", json={"type": "decision", "title": "Capacity is 6"}
    )
    response = await client.get("/api/system/export")
    assert response.status_code == 200
    assert "project-moah-backup-" in response.headers["content-disposition"]
    backup = tmp_path / "restored.db"
    backup.write_bytes(response.content)
    db = sqlite3.connect(backup)
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert db.execute("SELECT name FROM projects WHERE kind = 'project'").fetchall() == [
        ("Trailhead",)
    ]
    assert db.execute("SELECT title FROM memories").fetchall() == [("Capacity is 6",)]
    db.close()
    # A restored backup is a normal database: the app opens it and finds the same project.
    async with app_client(f"sqlite:///{backup}") as restored:
        assert [p["name"] for p in (await restored.get("/api/projects")).json()] == ["Trailhead"]


async def test_agent_command_matches_how_the_app_was_installed(
    client: AsyncClient, monkeypatch, tmp_path: Path
) -> None:
    import sys

    from app.services import system

    flatpak_info = tmp_path / ".flatpak-info"
    real_path = Path

    def fake_path(*parts):  # only the sandbox marker is redirected
        return flatpak_info if parts == ("/.flatpak-info",) else real_path(*parts)

    monkeypatch.setattr(system, "Path", fake_path)
    assert (await client.get("/api/system/agent-command")).json()["install"] == "source"

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "C:\\Moah\\resources\\bin\\project-brain-backend.exe")
    monkeypatch.setattr(sys, "platform", "win32")
    assert (await client.get("/api/system/agent-command")).json() == {
        "install": "windows",
        "command": ["C:\\Moah\\resources\\bin\\project-brain-backend.exe", "--mcp"],
    }

    monkeypatch.setattr(sys, "platform", "linux")
    launcher = tmp_path / "project-moah-mcp"
    launcher.write_text("#!/bin/sh\n")
    monkeypatch.setattr(system, "DEB_LAUNCHER", launcher)
    assert (await client.get("/api/system/agent-command")).json() == {
        "install": "deb",
        "command": ["project-moah-mcp"],
    }

    flatpak_info.write_text("[Application]\n")
    assert (await client.get("/api/system/agent-command")).json()["command"][:2] == [
        "flatpak",
        "run",
    ]

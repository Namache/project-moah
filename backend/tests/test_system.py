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

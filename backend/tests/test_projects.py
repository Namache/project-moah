from pathlib import Path

import pytest
from httpx import AsyncClient

from app.seed import seed_projects
from tests.conftest import app_client

pytestmark = pytest.mark.anyio


async def test_health_and_project_crud(client: AsyncClient) -> None:
    assert (await client.get("/api/health")).json() == {"status": "ok"}
    assert (await client.get("/api/projects")).json() == []

    created = await client.post(
        "/api/projects",
        json={
            "name": "  Trailhead  ",
            "description": "A game",
            "icon": "⛰️",
            "accent": "#D99A53",
            "root_path": "/tmp/future-repo",
        },
    )
    assert created.status_code == 201
    project = created.json()
    assert project["name"] == "Trailhead"
    assert project["slug"] == "trailhead"
    assert project["status"] == "active"
    assert project["current_focus_task_id"] is None
    assert project["root_path"] == "/tmp/future-repo"
    assert project["created_at"].endswith("Z")
    assert project["archived_at"] is None
    project_id = project["id"]

    assert (await client.get(f"/api/projects/{project_id}")).json() == project
    assert [item["id"] for item in (await client.get("/api/projects")).json()] == [project_id]

    updated = await client.patch(
        f"/api/projects/{project_id}",
        json={"name": "Trailhead Next", "description": None, "status": "paused"},
    )
    assert updated.status_code == 200
    changed = updated.json()
    assert changed["name"] == "Trailhead Next"
    assert changed["slug"] == "trailhead"
    assert changed["description"] is None
    assert changed["status"] == "paused"

    archived = await client.post(f"/api/projects/{project_id}/archive")
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    assert (await client.get("/api/projects")).json() == []
    assert (await client.get(f"/api/projects/{project_id}")).status_code == 200
    assert len((await client.get("/api/projects?include_archived=true")).json()) == 1

    restored = await client.patch(f"/api/projects/{project_id}", json={"status": "active"})
    assert restored.status_code == 200
    assert restored.json()["archived_at"] is None
    assert len((await client.get("/api/projects")).json()) == 1


async def test_validation_uniqueness_and_missing_project(client: AsyncClient) -> None:
    first = await client.post("/api/projects", json={"name": "My Project"})
    assert first.status_code == 201
    assert (await client.post("/api/projects", json={"name": "my project"})).status_code == 409
    assert (await client.post("/api/projects", json={"name": "  "})).status_code == 422
    assert (
        await client.post("/api/projects", json={"name": "Ok", "unexpected": True})
    ).status_code == 422
    assert (
        await client.post("/api/projects", json={"name": "Ok", "status": "bad"})
    ).status_code == 422
    assert (
        await client.post("/api/projects", json={"name": "Color", "accent": "red"})
    ).status_code == 422
    first_id = first.json()["id"]
    assert (await client.patch(f"/api/projects/{first_id}", json={})).status_code == 422
    assert (await client.patch(f"/api/projects/{first_id}", json={"name": None})).status_code == 422
    assert (await client.get("/api/projects/missing")).status_code == 404
    assert (await client.patch("/api/projects/missing", json={"name": "New"})).status_code == 404
    assert (await client.post("/api/projects/missing/archive")).status_code == 404

    second = await client.post("/api/projects", json={"name": "Other"})
    assert second.status_code == 201
    duplicate_rename = await client.patch(
        f"/api/projects/{second.json()['id']}", json={"name": "MY PROJECT"}
    )
    assert duplicate_rename.status_code == 409


async def test_slug_collision_gets_suffix(client: AsyncClient) -> None:
    first = (await client.post("/api/projects", json={"name": "Plan + Build"})).json()
    second = (await client.post("/api/projects", json={"name": "Plan / Build"})).json()
    assert first["slug"] == "plan-build"
    assert second["slug"] == "plan-build-2"


async def test_data_persists_across_app_instances(database_url: str) -> None:
    async with app_client(database_url) as first_client:
        project = (await first_client.post("/api/projects", json={"name": "Persistent"})).json()

    async with app_client(database_url) as second_client:
        assert (await second_client.get(f"/api/projects/{project['id']}")).json()[
            "name"
        ] == "Persistent"


async def test_two_projects_stay_separate(client: AsyncClient) -> None:
    trailhead = (await client.post("/api/projects", json={"name": "Trailhead"})).json()
    starling = (await client.post("/api/projects", json={"name": "Starling"})).json()
    assert trailhead["id"] != starling["id"]

    response = await client.patch(
        f"/api/projects/{trailhead['id']}",
        json={"description": "Trailhead only", "status": "completed"},
    )
    assert response.status_code == 200
    assert (await client.get(f"/api/projects/{starling['id']}")).json() == starling
    by_id = {project["id"]: project for project in (await client.get("/api/projects")).json()}
    assert by_id[trailhead["id"]]["description"] == "Trailhead only"
    assert by_id[starling["id"]]["description"] is None


async def test_root_path_is_stored_without_accessing_it(
    client: AsyncClient, tmp_path: Path
) -> None:
    future_repo = tmp_path / "not-created-yet" / "repo"
    response = await client.post(
        "/api/projects", json={"name": "Future", "root_path": str(future_repo)}
    )
    assert response.status_code == 201
    assert response.json()["root_path"] == str(future_repo)
    assert not future_repo.exists()

    assert (
        await client.post(
            "/api/projects", json={"name": "Relative", "root_path": "../another-project"}
        )
    ).status_code == 422
    assert (
        await client.patch(f"/api/projects/{response.json()['id']}", json={"root_path": "./repo"})
    ).status_code == 422
    assert (
        await client.patch(f"/api/projects/{response.json()['id']}", json={"root_path": None})
    ).json()["root_path"] is None


async def test_seed_is_idempotent_with_demo_tasks(database_url: str) -> None:
    assert seed_projects(database_url) == 3
    assert seed_projects(database_url) == 0
    async with app_client(database_url) as client:
        projects = {p["name"]: p for p in (await client.get("/api/projects")).json()}
        assert set(projects) == {"Trailhead", "Starling", "Greenline"}
        overviews = {
            o["project_id"]: o for o in (await client.get("/api/workspace/overviews")).json()
        }
        climb = overviews[projects["Trailhead"]["id"]]
        assert climb["active_milestone"]["name"] == "Demo 0.1.1"
        focus = climb["focus_task"]
        assert focus["human_id"] == "CAMP-001"
        assert (focus["criteria_completed"], focus["criteria_total"]) == (4, 5)
        assert focus["is_blocked_by_open_dependency"] is True
        assert overviews[projects["Starling"]["id"]]["focus_task"]["title"] == "Turn Order System"
        assert overviews[projects["Greenline"]["id"]]["focus_task"] is None
        total = len((await client.get("/api/tasks")).json())
    seed_projects(database_url)
    async with app_client(database_url) as client:
        assert len((await client.get("/api/tasks")).json()) == total == 4

"""Agent settings, "Work on task" prompts and second opinions."""

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient

from tests.conftest import app_client
from tests.test_mcp import agent, call

pytestmark = pytest.mark.anyio
# An absolute folder on every system; Windows folders are written with forward slashes.
ROOT = "C:/home/me/game" if sys.platform == "win32" else "/home/me/game"


async def make_task(client: AsyncClient, root: str | None = ROOT) -> tuple[str, dict]:
    body = {"name": "Game", **({"root_path": root} if root else {})}
    pid = (await client.post("/api/projects", json=body)).json()["id"]
    task = (
        await client.post(
            f"/api/projects/{pid}/tasks",
            json={
                "title": "Camp capacity",
                "description": "Raise the camp limit.",
                "acceptance_criteria": ["Six members fit", "Saves still load"],
                "next_action": "Update the constant",
            },
        )
    ).json()
    return pid, task


async def test_agent_settings_defaults_and_changes(client: AsyncClient) -> None:
    defaults = (await client.get("/api/settings/agents")).json()
    assert defaults == {
        "default_agent": "claude",
        "second_opinion_enabled": False,
        "codex_command": "codex",
        "claude_command": "claude",
    }
    changed = await client.patch(
        "/api/settings/agents",
        json={"default_agent": "codex", "codex_command": "  distrobox-host-exec codex  "},
    )
    assert changed.json()["default_agent"] == "codex"
    assert changed.json()["codex_command"] == "distrobox-host-exec codex"
    bad = await client.patch("/api/settings/agents", json={"default_agent": "gemini"})
    assert bad.status_code == 422


async def test_work_prompt_for_each_agent(client: AsyncClient) -> None:
    pid, task = await make_task(client)
    claude = (await client.get(f"/api/projects/{pid}/tasks/{task['human_id']}/work-prompt")).json()
    assert claude["agent"] == "claude" and claude["url"].startswith("claude://code/new?q=")
    prompt = claude["prompt"]
    assert task["human_id"] in prompt and "Six members fit" in prompt and ROOT in prompt
    assert "brain_context_pack" in prompt and "brain_create_checkpoint" in prompt
    assert parse_qs(urlsplit(claude["url"]).query)["q"] == [prompt]

    await client.patch("/api/settings/agents", json={"default_agent": "codex"})
    codex = (await client.get(f"/api/projects/{pid}/tasks/{task['human_id']}/work-prompt")).json()
    query = parse_qs(urlsplit(codex["url"]).query)
    assert codex["url"].startswith("codex://new?") and query["path"] == [ROOT]
    assert query["prompt"] == [codex["prompt"]]
    # The agent can still be chosen per click.
    other = await client.get(
        f"/api/projects/{pid}/tasks/{task['human_id']}/work-prompt", params={"agent": "claude"}
    )
    assert other.json()["agent"] == "claude"


async def test_long_descriptions_stay_within_link_limits(client: AsyncClient) -> None:
    pid, task = await make_task(client)
    await client.patch(
        f"/api/projects/{pid}/tasks/{task['human_id']}", json={"description": "x" * 20000}
    )
    result = (await client.get(f"/api/projects/{pid}/tasks/{task['human_id']}/work-prompt")).json()
    assert len(result["prompt"]) <= 4500


async def test_second_opinion_is_off_until_switched_on(database_url: str, tmp_path: Path) -> None:
    async with app_client(database_url) as client:
        pid, task = await make_task(client)
    async with agent(database_url, "claude") as session:
        failed, message = await call(
            session, "brain_second_opinion", question="Is 6 right?", project=pid
        )
        assert failed and "switched off" in message

    async with app_client(database_url) as client:
        await client.patch(
            "/api/settings/agents",
            json={"second_opinion_enabled": True, "codex_command": "distrobox-host-exec codex"},
        )
    async with agent(database_url, "claude") as session:
        failed, result = await call(
            session,
            "brain_second_opinion",
            question="Is a camp limit of 6 right?",
            task=task["human_id"],
            project=pid,
        )
        assert not failed and result["other_agent"] == "codex"
        command = result["command"]
        assert command.startswith("distrobox-host-exec codex exec --sandbox read-only")
        assert f"-C {ROOT}" in command and "Is a camp limit of 6 right?" in command
        assert "Six members fit" in command and command.rstrip().endswith("PB_SECOND_OPINION")
        assert "side by side" in result["instructions"]

    async with agent(database_url, "codex") as session:
        failed, result = await call(
            session, "brain_second_opinion", question="Second look?", project=pid
        )
        assert not failed and result["other_agent"] == "claude"
        assert result["command"].startswith(f"cd {ROOT} && claude -p --permission-mode plan")

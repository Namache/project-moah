import json
import tomllib
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.services import agent_connect

EXE = "C:\\Program Files\\Moah\\project-brain-backend.exe"
LAUNCH = {"install": "windows", "command": [EXE, "--mcp"]}


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def statuses(results: list[dict]) -> dict[str, str]:
    return {result["agent"]: result["status"] for result in results}


def test_skips_agents_that_are_not_installed(home: Path) -> None:
    assert statuses(agent_connect.connect_agents(LAUNCH)) == {
        "claude": "not_found",
        "codex": "not_found",
    }
    assert list(home.iterdir()) == []


def test_connects_codex_and_keeps_its_settings(home: Path) -> None:
    (home / ".codex").mkdir()
    config = home / ".codex/config.toml"
    original = 'model = "gpt"\r\n\r\n[windows]\r\nsandbox = "elevated"\r\n'
    config.write_bytes(original.encode())

    for _ in range(2):
        assert statuses(agent_connect.connect_agents(LAUNCH))["codex"] == "connected"

    saved = tomllib.loads(config.read_text(encoding="utf-8"))
    assert saved["model"] == "gpt" and saved["windows"]["sandbox"] == "elevated"
    assert saved["mcp_servers"]["project-moah"] == {
        "command": EXE,
        "args": ["--mcp", "--agent", "codex"],
        "startup_timeout_sec": 20,
    }
    assert config.read_text(encoding="utf-8").count("[mcp_servers.project-moah]") == 1
    assert (home / ".codex/AGENTS.md").read_text(encoding="utf-8").count("brain_brief") == 1
    assert (home / ".codex/config.toml.moah-backup").read_bytes() == original.encode()


def test_moves_a_codex_connection_to_this_install_without_touching_the_next_section(
    home: Path,
) -> None:
    (home / ".codex").mkdir()
    (home / ".codex/config.toml").write_text(
        '[mcp_servers.project-moah]\ncommand = "old.exe"\n\n[windows]\nsandbox = "elevated"\n'
    )
    agent_connect.connect_codex(LAUNCH["command"])
    saved = tomllib.loads((home / ".codex/config.toml").read_text(encoding="utf-8"))
    assert saved["mcp_servers"]["project-moah"]["command"] == EXE
    assert saved["windows"]["sandbox"] == "elevated"


def test_connects_claude_and_keeps_other_servers_and_hooks(home: Path) -> None:
    (home / ".claude").mkdir()
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"other": {}}, "theme": "dark"}))
    other_hook = {"matcher": "startup", "hooks": [{"type": "command", "command": "other"}]}
    (home / ".claude/settings.json").write_text(
        json.dumps({"model": "x", "hooks": {"SessionStart": [other_hook]}})
    )

    for _ in range(2):
        assert statuses(agent_connect.connect_agents(LAUNCH))["claude"] == "connected"

    config = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    assert config["theme"] == "dark" and "other" in config["mcpServers"]
    assert config["mcpServers"]["project-moah"]["args"] == ["--mcp", "--agent", "claude"]
    settings = json.loads((home / ".claude/settings.json").read_text(encoding="utf-8"))
    assert settings["model"] == "x"
    groups = settings["hooks"]["SessionStart"]
    assert groups[0] == other_hook and len(groups) == 2
    assert "--brief" in str(groups[1]["hooks"][0])


def test_a_damaged_settings_file_is_reported_and_left_alone(home: Path) -> None:
    (home / ".claude").mkdir()
    (home / ".claude.json").write_text("{ not json")
    result = agent_connect.connect_agents(LAUNCH)[0]
    assert result["status"] == "failed" and result["detail"]
    assert (home / ".claude.json").read_text() == "{ not json"


def test_a_write_the_system_refuses_is_reported(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (home / ".codex").mkdir()

    def refuse(*_: object) -> None:
        raise PermissionError("Access is denied")

    monkeypatch.setattr(agent_connect.os, "replace", refuse)
    results = {r["agent"]: r for r in agent_connect.connect_agents(LAUNCH)}
    assert results["codex"]["status"] == "failed"
    assert "denied" in results["codex"]["detail"]


def test_sandboxed_installs_are_sent_to_help(home: Path) -> None:
    (home / ".codex").mkdir()
    results = agent_connect.connect_agents({"install": "flatpak", "command": ["flatpak"]})
    assert {result["status"] for result in results} == {"failed"}
    assert not (home / ".codex/config.toml").exists()


def test_exit_code_says_when_a_person_is_needed(
    home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent_connect, "agent_launch", lambda: LAUNCH)
    assert agent_connect.main() == 1
    (home / ".codex").mkdir()
    assert agent_connect.main() == 0
    assert "Codex: connected" in capsys.readouterr().out


@pytest.mark.anyio
async def test_connect_button_endpoint(
    client: AsyncClient, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent_connect, "agent_launch", lambda: LAUNCH)
    response = await client.post("/api/system/connect-agents")
    assert response.status_code == 200
    assert statuses(response.json()["results"]) == {"claude": "not_found", "codex": "not_found"}

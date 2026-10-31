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


def test_windows_brief_hook_is_one_line_that_cmd_and_git_bash_both_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_connect.sys, "platform", "win32")
    hook = agent_connect._brief_hook(LAUNCH["command"])
    # Claude Code has no "args" field: anything outside "command" is dropped and the bare path,
    # cut at its first space, fails. The brief reads CLAUDE_PROJECT_DIR itself.
    assert hook == {"type": "command", "command": f'"{EXE}" --mcp --brief', "timeout": 20}


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


FLATPAK = {"install": "flatpak", "command": ["flatpak", "run", "--command=project-moah-mcp", "x"]}
# The [Context] Flatpak writes for the app, as on a real Bazzite install, without and with
# the one-run home access. A shared folder under /home is not the home folder.
SANDBOX = "[Context]\nfilesystems=/home/me/game:ro;~/.claude/projects:ro;~/.codex/sessions:ro;\n"
ONE_RUN = "[Context]\nfilesystems=home;/home/me/game:ro;~/.claude/projects:ro;\n"


def test_the_sandboxed_flatpak_gives_the_one_command(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (home / ".codex").mkdir()
    (home / "flatpak-info").write_text(SANDBOX)
    monkeypatch.setattr(agent_connect, "FLATPAK_INFO", home / "flatpak-info")
    results = agent_connect.connect_agents(FLATPAK)
    assert {result["status"] for result in results} == {"failed"}
    assert agent_connect.FLATPAK_CONNECT in results[0]["detail"]
    assert "--filesystem=home" in agent_connect.FLATPAK_CONNECT
    assert not (home / ".codex/config.toml").exists()
    monkeypatch.setattr(agent_connect, "agent_launch", lambda: FLATPAK)
    assert agent_connect.main() == 1
    printed = capsys.readouterr().out
    assert agent_connect.FLATPAK_CONNECT in printed and "Help page" not in printed


def test_the_flatpak_connects_when_run_with_home_access(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (home / ".codex").mkdir()
    (home / "flatpak-info").write_text(ONE_RUN)
    monkeypatch.setattr(agent_connect, "FLATPAK_INFO", home / "flatpak-info")
    assert statuses(agent_connect.connect_agents(FLATPAK))["codex"] == "connected"
    saved = tomllib.loads((home / ".codex/config.toml").read_text(encoding="utf-8"))
    assert saved["mcp_servers"]["project-moah"]["command"] == "flatpak"


def test_replaces_the_old_project_brain_connection(home: Path) -> None:
    (home / ".claude").mkdir()
    old = {"command": "flatpak", "args": ["run", "--command=project-brain-mcp"]}
    other = {"command": "someone-elses-brain"}
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"project-brain": old}}))
    agent_connect.connect_claude(LAUNCH["command"])
    servers = json.loads((home / ".claude.json").read_text(encoding="utf-8"))["mcpServers"]
    assert list(servers) == ["project-moah"]
    # A server that only shares the old name is someone else's, and stays.
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"project-brain": other}}))
    agent_connect.connect_claude(LAUNCH["command"])
    servers = json.loads((home / ".claude.json").read_text(encoding="utf-8"))["mcpServers"]
    assert servers["project-brain"] == other

    (home / ".codex").mkdir()
    (home / ".codex/config.toml").write_text(
        '[mcp_servers.project-brain]\ncommand = "flatpak"\nargs = ["--command=project-brain-mcp"]\n'
        '\n[windows]\nsandbox = "elevated"\n'
    )
    agent_connect.connect_codex(LAUNCH["command"])
    saved = tomllib.loads((home / ".codex/config.toml").read_text(encoding="utf-8"))
    assert list(saved["mcp_servers"]) == ["project-moah"]
    assert saved["windows"]["sandbox"] == "elevated"


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

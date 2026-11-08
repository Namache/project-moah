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


def test_connects_the_hooks_that_catch_questions_asked_in_the_chat(home: Path) -> None:
    (home / ".claude").mkdir()
    (home / ".codex").mkdir()
    own_stop = {"hooks": [{"type": "command", "command": "notify-send done"}]}
    (home / ".claude/settings.json").write_text(json.dumps({"hooks": {"Stop": [own_stop]}}))
    (home / ".codex/hooks.json").write_text(json.dumps({"description": "mine", "hooks": {}}))

    for _ in range(2):  # connecting again replaces Project Moah's hooks, never adds a second
        assert statuses(agent_connect.connect_agents(LAUNCH)) == {
            "claude": "connected",
            "codex": "connected",
        }

    claude = json.loads((home / ".claude/settings.json").read_text(encoding="utf-8"))["hooks"]
    assert claude["Stop"][0] == own_stop and len(claude["Stop"]) == 2
    stop = claude["Stop"][1]["hooks"][0]
    assert stop["command"].endswith("--mcp --agent claude --hook stop") and "async" not in stop
    [prompt_group] = claude["UserPromptSubmit"]
    # Claude Code sends the person's message without waiting for Project Moah.
    assert prompt_group["hooks"][0]["async"] is True
    assert prompt_group["hooks"][0]["command"].endswith("--agent claude --hook prompt")
    codex = json.loads((home / ".codex/hooks.json").read_text(encoding="utf-8"))
    assert codex["description"] == "mine" and set(codex["hooks"]) == {"Stop", "UserPromptSubmit"}
    assert [len(groups) for groups in codex["hooks"].values()] == [1, 1]
    assert codex["hooks"]["Stop"][0]["hooks"][0]["command"].endswith("--agent codex --hook stop")
    assert "async" not in codex["hooks"]["UserPromptSubmit"][0]["hooks"][0]


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


def test_the_flatpak_hands_claude_codes_session_to_the_server(
    home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A Flatpak started from a container gets none of Claude Code's environment, so a shell
    passes the session id on as an argument: without it Moah can't match the person's reply
    in the chat to the question it answers."""
    import subprocess

    (home / ".claude").mkdir()
    (home / "flatpak-info").write_text(ONE_RUN)
    monkeypatch.setattr(agent_connect, "FLATPAK_INFO", home / "flatpak-info")
    assert statuses(agent_connect.connect_agents(FLATPAK))["claude"] == "connected"
    server = json.loads((home / ".claude.json").read_text(encoding="utf-8"))["mcpServers"][
        "project-moah"
    ]
    assert server["command"] == "sh" and server["args"][0] == "-c"
    # Run it as Claude Code would, with a stand-in flatpak that prints what it was given.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "flatpak").write_text('#!/bin/sh\nprintf "%s|" "$@"\n')
    (bin_dir / "flatpak").chmod(0o755)
    for session, expected in (("0b5e8c1a-2f4d", "0b5e8c1a-2f4d"), (None, "")):
        env = {"PATH": f"{bin_dir}:/usr/bin:/bin"}
        if session:
            env["CLAUDE_CODE_SESSION_ID"] = session
        ran = subprocess.run(
            [server["command"], *server["args"]], env=env, capture_output=True, text=True
        )
        assert ran.stdout.split("|")[:-1] == [
            "run",
            "--command=project-moah-mcp",
            "x",
            "--agent",
            "claude",
            "--session-id",
            expected,
        ]
    # Other installs get the environment and start the server directly, as before.
    assert agent_connect._claude_server(LAUNCH["command"])["command"] == EXE


def test_refresh_at_start_moves_connected_agents_to_this_install(home: Path) -> None:
    """After an update or a move to another folder, agents connected before keep working: the
    app points them at itself when it starts, and nobody presses Connect again."""
    (home / ".claude").mkdir()
    (home / ".codex").mkdir()
    old = {"type": "stdio", "command": "old.exe", "args": ["--mcp"], "env": {"MY_VAR": "1"}}
    servers = {"project-moah": old, "other": {"command": "x"}}
    (home / ".claude.json").write_text(json.dumps({"mcpServers": servers, "theme": "dark"}))
    (home / ".codex/config.toml").write_text(
        'model = "gpt"\n\n[mcp_servers.project-moah]\ncommand = "old.exe"\nargs = ["--mcp"]\n'
    )
    (home / ".codex/AGENTS.md").write_text("My own notes.\n")

    assert agent_connect.refresh_connections(LAUNCH) == ["claude", "codex"]

    config = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    server = config["mcpServers"]["project-moah"]
    assert server["command"] == EXE and server["args"] == ["--mcp", "--agent", "claude"]
    assert server["env"] == {"MY_VAR": "1"}  # the person's own variables stay
    assert config["theme"] == "dark" and config["mcpServers"]["other"] == {"command": "x"}
    settings = json.loads((home / ".claude/settings.json").read_text(encoding="utf-8"))
    assert set(settings["hooks"]) == {"SessionStart", "Stop", "UserPromptSubmit"}
    saved = tomllib.loads((home / ".codex/config.toml").read_text(encoding="utf-8"))
    assert saved["model"] == "gpt" and saved["mcp_servers"]["project-moah"]["command"] == EXE
    # Once connected, AGENTS.md is the person's: a refresh doesn't add the brief line back.
    assert (home / ".codex/AGENTS.md").read_text(encoding="utf-8") == "My own notes.\n"


def test_refresh_leaves_agents_alone_that_were_never_connected_or_are_current(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (home / ".claude").mkdir()
    (home / ".codex").mkdir()
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"other": {}}}))
    (home / ".codex/config.toml").write_text('model = "gpt"\n')

    assert agent_connect.refresh_connections(LAUNCH) == []
    files = sorted(path.name for path in home.rglob("*") if path.is_file())
    assert files == [".claude.json", "config.toml"]  # no hooks, no brief, no backups

    agent_connect.connect_agents(LAUNCH)
    writes: list[Path] = []
    monkeypatch.setattr(agent_connect, "_write", lambda path, _text: writes.append(path))
    # Claude Code rewrites its own file all the time: an unchanged connection isn't written.
    assert agent_connect.refresh_connections(LAUNCH) == ["claude", "codex"]
    assert writes == []


def test_refresh_never_stops_the_app(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (home / ".claude").mkdir()
    (home / ".claude.json").write_text("{ not json")
    logged: list[tuple[str, str]] = []
    monkeypatch.setattr(
        agent_connect.error_log,
        "write",
        lambda source, message, *_, **__: logged.append((source, message)),
    )
    assert agent_connect.refresh_connections(LAUNCH) == []
    assert [source for source, _ in logged] == ["service"] and "claude" in logged[0][1]
    assert (home / ".claude.json").read_text() == "{ not json"


def test_refresh_does_nothing_where_the_app_cant_change_agent_settings(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (home / ".codex").mkdir()
    original = '[mcp_servers.project-moah]\ncommand = "old.exe"\n'
    (home / ".codex/config.toml").write_text(original)
    (home / "flatpak-info").write_text(SANDBOX)
    monkeypatch.setattr(agent_connect, "FLATPAK_INFO", home / "flatpak-info")
    source = {"install": "source", "command": ["python", "-m", "app.mcp"]}
    for launch in (FLATPAK, source):
        assert agent_connect.refresh_connections(launch) == []
    assert (home / ".codex/config.toml").read_text() == original


def test_an_old_flatpak_connection_is_told_how_to_refresh(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sandboxed Flatpak can't rewrite an agent's settings, so the agent hears how to, once
    per session, when its connection predates the session id and the id didn't arrive."""
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setattr(agent_connect, "FLATPAK_INFO", home / "flatpak-info")
    assert agent_connect.connection_notice("claude", None) is None  # not a Flatpak
    (home / "flatpak-info").write_text(SANDBOX)
    notice = agent_connect.connection_notice("claude", None)
    assert notice and agent_connect.FLATPAK_CONNECT in notice
    assert agent_connect.connection_notice("claude", "") is None  # Connect's entry, no id set
    assert agent_connect.connection_notice("codex", None) is None
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "0b5e8c1a-2f4d")
    assert agent_connect.connection_notice("claude", None) is None  # the id arrived anyway


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


def test_writing_settings_keeps_their_permissions(tmp_path) -> None:
    """A private settings file stays private after Moah rewrites it."""
    import os
    import stat

    from app.services.agent_connect import _write

    config = tmp_path / ".claude.json"
    config.write_text("{}")
    os.chmod(config, 0o600)
    _write(config, '{"mcpServers": {}}\n')
    assert stat.S_IMODE(config.stat().st_mode) == 0o600

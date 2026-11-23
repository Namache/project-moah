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
    assert set(claude) == {"SessionStart", "Stop", "UserPromptSubmit", "PostToolUse"}
    assert claude["Stop"][0] == own_stop and len(claude["Stop"]) == 2
    assert [len(claude[event]) for event in ("UserPromptSubmit", "PostToolUse")] == [1, 1]
    stop, wait = claude["Stop"][1]["hooks"]
    assert stop["command"].endswith("--agent claude --hook stop --settle")
    assert wait["command"].endswith("--agent claude --hook wait")
    codex = json.loads((home / ".codex/hooks.json").read_text(encoding="utf-8"))
    assert codex["description"] == "mine"
    assert set(codex["hooks"]) == {"Stop", "UserPromptSubmit", "PostToolUse"}
    assert [len(groups) for groups in codex["hooks"].values()] == [1, 1, 1]


def test_windows_brief_hook_is_one_line_that_cmd_and_git_bash_both_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_connect.sys, "platform", "win32")
    hook = agent_connect._brief_hook(LAUNCH["command"])
    # Claude Code has no "args" field: anything outside "command" is dropped and the bare path,
    # cut at its first space, fails. The brief reads CLAUDE_PROJECT_DIR itself.
    assert hook == {"type": "command", "command": f'"{EXE}" --mcp --brief', "timeout": 20}


REAL_FLATPAK = {
    "install": "flatpak",
    "command": [
        "flatpak",
        "run",
        "--command=project-moah-mcp",
        "io.github.projectbrain.ProjectBrain",
    ],
}
FP = "flatpak run --command=project-moah-mcp io.github.projectbrain.ProjectBrain"
MATCHER = "mcp__project[-_](moah|brain)__brain_.*"


def test_claude_hooks_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    """The set Connect writes for Claude Code (chat_wait.py has the reasons): the Stop group runs
    the recording (async, after a short wait) and the waiting that wakes the chat (asyncRewake);
    the prompt hook hands over what was not delivered; the tool hook learns each call's chat."""
    monkeypatch.setattr(agent_connect.sys, "platform", "linux")
    assert agent_connect._claude_hooks(REAL_FLATPAK["command"]) == {
        "SessionStart": {
            "matcher": "startup|clear|compact",
            "hooks": [
                {
                    "type": "command",
                    "command": f'{FP} --brief --cwd "$CLAUDE_PROJECT_DIR"',
                    "timeout": 20,
                }
            ],
        },
        "Stop": {
            "hooks": [
                {
                    "type": "command",
                    "command": f"{FP} --agent claude --hook stop --settle",
                    "async": True,
                    "timeout": 60,
                },
                {
                    "type": "command",
                    "command": f"{FP} --agent claude --hook wait",
                    "asyncRewake": True,
                    "timeout": 86400,
                },
            ]
        },
        "UserPromptSubmit": {
            "hooks": [
                {
                    "type": "command",
                    "command": f"{FP} --agent claude --hook prompt --deliver",
                    "asyncRewake": True,
                    "timeout": 60,
                }
            ]
        },
        "PostToolUse": {
            "matcher": MATCHER,
            "hooks": [
                {
                    "type": "command",
                    "command": f"{FP} --agent claude --hook tool",
                    "async": True,
                    "timeout": 30,
                }
            ],
        },
    }


def test_claude_hook_lines_for_windows_and_for_a_path_with_a_space(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def commands(command: list[str]) -> list[str]:
        groups = agent_connect._claude_hooks(command)
        return [
            h["command"]
            for event in ("Stop", "UserPromptSubmit", "PostToolUse")
            for h in groups[event]["hooks"]
        ]

    monkeypatch.setattr(agent_connect.sys, "platform", "win32")
    assert commands(LAUNCH["command"]) == [
        f'"{EXE}" --mcp --agent claude --hook stop --settle',
        f'"{EXE}" --mcp --agent claude --hook wait',
        f'"{EXE}" --mcp --agent claude --hook prompt --deliver',
        f'"{EXE}" --mcp --agent claude --hook tool',
    ]
    monkeypatch.setattr(agent_connect.sys, "platform", "linux")
    assert commands(["/opt/Project Moah/moah-mcp"])[1] == (
        "'/opt/Project Moah/moah-mcp' --agent claude --hook wait"
    )


def test_codex_hooks_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Codex runs every hook in turn and waits for it, so none is async. Where Moah is not
    sandboxed Stop is the line it always was; the Flatpak's Stop line starts the waiter."""
    from app.services.codex_waiter import flatpak_stop_line

    monkeypatch.setattr(agent_connect.sys, "platform", "win32")
    assert agent_connect._codex_hooks(LAUNCH["command"]) == {
        "Stop": {
            "hooks": [
                {
                    "type": "command",
                    "command": f'"{EXE}" --mcp --agent codex --hook stop',
                    "timeout": 15,
                }
            ]
        },
        "UserPromptSubmit": {
            "hooks": [
                {
                    "type": "command",
                    "command": f'"{EXE}" --mcp --agent codex --hook prompt',
                    "timeout": 15,
                }
            ]
        },
        "PostToolUse": {
            "matcher": MATCHER,
            "hooks": [
                {
                    "type": "command",
                    "command": f'"{EXE}" --mcp --agent codex --hook tool',
                    "timeout": 30,
                }
            ],
        },
    }
    monkeypatch.setattr(agent_connect.sys, "platform", "linux")
    flatpak = agent_connect._codex_hooks(REAL_FLATPAK["command"])
    stop = flatpak["Stop"]["hooks"][0]
    assert stop == {
        "type": "command",
        "command": flatpak_stop_line(REAL_FLATPAK["command"]),
        "timeout": 15,
    }
    assert stop["command"].startswith(f'd=$(cat); printf %s "$d" | {FP} --agent codex --hook stop')
    assert flatpak["UserPromptSubmit"]["hooks"] == [
        {"type": "command", "command": f"{FP} --agent codex --hook prompt", "timeout": 15}
    ]
    assert flatpak["PostToolUse"]["hooks"] == [
        {"type": "command", "command": f"{FP} --agent codex --hook tool", "timeout": 30}
    ]
    # Any other install runs the plain Stop hook: the waiter starts from Moah's own Python.
    deb = agent_connect._codex_hooks(["project-moah-mcp"])["Stop"]["hooks"][0]
    assert deb["command"] == "project-moah-mcp --agent codex --hook stop"


@pytest.mark.parametrize(
    ("platform", "launch", "stop", "prompt"),
    [
        (
            "win32",
            LAUNCH,
            f'"{EXE}" --mcp --agent codex --hook stop',
            f'"{EXE}" --mcp --agent codex --hook prompt',
        ),
        (
            "linux",
            {"install": "deb", "command": ["project-moah-mcp"]},
            "project-moah-mcp --agent codex --hook stop",
            "project-moah-mcp --agent codex --hook prompt",
        ),
    ],
)
def test_connecting_again_leaves_codexs_old_hook_lines_byte_for_byte(
    home: Path, monkeypatch: pytest.MonkeyPatch, platform: str, launch: dict, stop: str, prompt: str
) -> None:
    """Codex asks the person to trust a hook again when its definition changes. The Stop and
    prompt hooks of the earlier versions are not changed, so only the new tool hook asks."""
    monkeypatch.setattr(agent_connect.sys, "platform", platform)
    (home / ".codex").mkdir()
    old = {
        "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": stop, "timeout": 15}]}],
            "UserPromptSubmit": [
                {"hooks": [{"type": "command", "command": prompt, "timeout": 15}]}
            ],
        }
    }
    path = home / ".codex/hooks.json"
    path.write_text(json.dumps(old, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    assert statuses(agent_connect.connect_agents(launch))["codex"] == "connected"
    new = json.loads(path.read_text(encoding="utf-8"))["hooks"]

    def text(entry: object) -> str:  # key order counts: it is the text Codex hashes
        return json.dumps(entry, indent=2, ensure_ascii=False)

    assert text(new["Stop"]) == text(old["hooks"]["Stop"])
    assert text(new["UserPromptSubmit"]) == text(old["hooks"]["UserPromptSubmit"])
    assert new["PostToolUse"][0]["hooks"][0]["command"].endswith("--agent codex --hook tool")
    before = path.read_bytes()
    agent_connect.connect_agents(launch)
    assert path.read_bytes() == before  # and again changes nothing


def test_the_flatpaks_waiting_stop_line_is_written_only_for_the_flatpak(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent_connect.sys, "platform", "linux")
    (home / ".codex").mkdir()
    (home / "flatpak-info").write_text(ONE_RUN)
    monkeypatch.setattr(agent_connect, "FLATPAK_INFO", home / "flatpak-info")
    lines = {}
    for name, launch in (
        ("flatpak", REAL_FLATPAK),
        ("deb", {"install": "deb", "command": ["moah"]}),
    ):
        agent_connect.connect_agents(launch)
        hooks = json.loads((home / ".codex/hooks.json").read_text(encoding="utf-8"))["hooks"]
        lines[name] = hooks["Stop"][0]["hooks"][0]["command"]
    assert "setsid" in lines["flatpak"] and "codex queue" in lines["flatpak"]
    assert lines["deb"] == "moah --agent codex --hook stop"


def test_a_persons_own_hook_that_says_brief_is_not_moahs(home: Path) -> None:
    """Only a hook that starts Moah is replaced: `git diff --brief` stays."""
    own = {"type": "command", "command": "git diff --brief"}
    assert not agent_connect._is_ours(own)
    assert not agent_connect._is_ours({"type": "command", "command": "my-tool --hook stop"})
    assert agent_connect._is_ours({"command": f'{FP} --brief --cwd "$CLAUDE_PROJECT_DIR"'})
    assert agent_connect._is_ours({"command": f"{FP} --agent claude --hook wait"})
    (home / ".claude").mkdir()
    (home / ".claude/settings.json").write_text(
        json.dumps({"hooks": {"SessionStart": [{"hooks": [own]}]}})
    )
    agent_connect.connect_claude(LAUNCH["command"])
    groups = json.loads((home / ".claude/settings.json").read_text(encoding="utf-8"))["hooks"]
    assert groups["SessionStart"][0] == {"hooks": [own]} and len(groups["SessionStart"]) == 2


def test_connecting_replaces_the_earlier_hook_set_without_a_second_copy(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What 0.4.3 wrote (stop and prompt hooks, no waiting) becomes the new set, one group per
    event, and the person's own hooks stay where they were."""
    monkeypatch.setattr(agent_connect.sys, "platform", "win32")
    (home / ".claude").mkdir()
    own = {"hooks": [{"type": "command", "command": "notify-send done"}]}
    brief = {"type": "command", "command": f'"{EXE}" --mcp --brief', "timeout": 20}
    stop = {
        "type": "command",
        "command": f'"{EXE}" --mcp --agent claude --hook stop',
        "timeout": 15,
    }
    prompt = {**stop, "command": f'"{EXE}" --mcp --agent claude --hook prompt', "async": True}
    (home / ".claude/settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [{"matcher": "startup", "hooks": [brief]}],
                    "Stop": [own, {"hooks": [stop]}],
                    "UserPromptSubmit": [{"hooks": [prompt]}],
                }
            }
        )
    )
    agent_connect.connect_claude(LAUNCH["command"])
    hooks = json.loads((home / ".claude/settings.json").read_text(encoding="utf-8"))["hooks"]
    assert hooks["Stop"][0] == own and len(hooks["Stop"]) == 2
    assert hooks["Stop"][1] == agent_connect._claude_hooks(LAUNCH["command"])["Stop"]
    assert hooks["UserPromptSubmit"] == [
        agent_connect._claude_hooks(LAUNCH["command"])["UserPromptSubmit"]
    ]
    assert len(hooks["SessionStart"]) == 1 and "PostToolUse" in hooks


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
    assert set(settings["hooks"]) == {"SessionStart", "Stop", "UserPromptSubmit", "PostToolUse"}
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
    monkeypatch.setattr(agent_connect, "data_folder", lambda: home / "moah-data")
    source = {"install": "source", "command": ["python", "-m", "app.mcp"]}
    for launch in (FLATPAK, source):
        assert agent_connect.refresh_connections(launch) == []
    assert (home / ".codex/config.toml").read_text() == original
    # The sandboxed Flatpak looks at the hook files only (test_hook_refresh.py): no hooks there,
    # so nothing was added and no backup made.
    assert not (home / ".codex/hooks.json").exists() and not (home / "moah-data").exists()


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
    private = stat.S_IMODE(config.stat().st_mode)  # Windows keeps only a read-only flag
    _write(config, '{"mcpServers": {}}\n')
    assert stat.S_IMODE(config.stat().st_mode) == private

"""Connect Claude Code and Codex to this installation in one step.

Writes the same settings Help lists by hand. Other settings in those files are kept, a first
backup is saved next to each changed file, and running it again changes nothing new.

People connect once. After an update, the app refreshes the connections it finds when it starts
(`refresh_connections`), and the sandboxed Flatpak, which can't, has Moah tell the agent how
(`connection_notice`).
"""

from __future__ import annotations

import configparser
import copy
import json
import os
import re
import shlex
import shutil
import sys
import tomllib
from pathlib import Path

from app.core import error_log
from app.services.agent_sessions import SESSION_ENV
from app.services.system import FLATPAK_ID, agent_launch
from app.services.usage import claude_home, codex_home

SERVER_NAME = "project-moah"
OLD_SERVER_NAME = "project-brain"  # this app's earlier name: replaced, so agents don't get two
FLATPAK_INFO = Path("/.flatpak-info")
# The Flatpak's sandbox keeps it out of agents' settings; this one run may write the home folder.
FLATPAK_CONNECT = f"flatpak run --filesystem=home --command=project-moah-mcp {FLATPAK_ID} --connect"
CODEX_SECTION = re.compile(rf"^\[mcp_servers\.{SERVER_NAME}\].*\n?(?:(?!\[).*\n?)*", re.MULTILINE)
OLD_CODEX_SECTION = re.compile(
    rf"^\[mcp_servers\.{OLD_SERVER_NAME}\].*\n?(?:(?!\[).*\n?)*", re.MULTILINE
)
CODEX_BRIEF = (
    "Project Moah is the source of truth for my rules and memory. At the start of every session, "
    "call\nthe project-moah tool brain_brief with your working folder as cwd and follow what it "
    "returns.\n"
)


def flatpak_home_access() -> bool:
    """Whether this Flatpak run may write the home folder, as FLATPAK_CONNECT allows."""
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(FLATPAK_INFO.read_text(encoding="utf-8"))
    except (OSError, configparser.Error):
        return False
    granted = parser.get("Context", "filesystems", fallback="").split(";")
    return any(entry in ("home", "home:rw", "host", "host:rw") for entry in granted)


def blocked_reason(launch: dict) -> str | None:
    """Why this install can't change agent settings, or None when it can."""
    if launch["install"] == "source":
        return "This install can't change agent settings. Use the commands in Help."
    if launch["install"] == "flatpak" and not flatpak_home_access():
        return f"The Flatpak's sandbox keeps it out. Run this in a terminal: {FLATPAK_CONNECT}"
    return None


def _ours(text: str) -> bool:
    """Whether an agent's server entry starts Project Moah (under any of its names)."""
    return re.search(r"projectbrain|project-brain|project-moah", text, re.IGNORECASE) is not None


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8") if path.exists() else ""


def _write(path: Path, text: str) -> None:
    """Replace a file in one step, so a failure can't leave half of someone's settings."""
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_name(f"{path.name}.moah-backup")
    if path.exists() and not backup.exists():
        shutil.copy2(path, backup)
    temporary = path.with_name(f"{path.name}.moah-new")
    temporary.write_bytes(text.encode("utf-8"))
    if path.exists():
        # Keep the file's permissions: ~/.claude.json is often private (0600), and a fresh
        # file would take the default ones and be readable by every account on the computer.
        shutil.copymode(path, temporary)
    os.replace(temporary, path)


def _read_json(path: Path) -> dict:
    text = _read(path).strip()
    data = json.loads(text) if text else {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a settings file")
    return data


def _line(parts: list[str]) -> str:
    """One shell line. Claude Code and Codex run hooks through a shell and have no "args"
    field; on Windows that shell is cmd.exe or Git Bash, which both read double quotes."""
    if sys.platform == "win32":
        return " ".join(f'"{part}"' if " " in part else part for part in parts)
    return shlex.join(parts)


def _brief_hook(command: list[str]) -> dict:
    # cmd.exe and Git Bash spell "$VAR" differently, so on Windows the brief reads the folder
    # itself.
    if sys.platform == "win32":
        return {"type": "command", "command": _line([*command, "--brief"]), "timeout": 20}
    line = f'{_line([*command, "--brief", "--cwd"])} "$CLAUDE_PROJECT_DIR"'
    return {"type": "command", "command": line, "timeout": 20}


def _turn_hook(command: list[str], agent: str, hook: str) -> dict:
    """The hook that catches a question the agent stops on (stop), or the person's reply to it
    (prompt): services/chat_questions.py. It prints nothing and never fails the turn."""
    entry = {
        "type": "command",
        "command": _line([*command, "--agent", agent, "--hook", hook]),
        "timeout": 15,
    }
    if agent == "claude" and hook == "prompt":
        entry["async"] = True  # Claude Code sends the message without waiting for it
    return entry


def _is_ours(hook: object) -> bool:
    text = str(hook)
    return "--brief" in text or ("--hook" in text and _ours(text))


def _with_hooks(settings: dict, groups_by_event: dict[str, dict]) -> dict:
    """Settings with exactly one Project Moah hook group per event, keeping every other hook."""
    hooks = settings.setdefault("hooks", {})
    for event, group in groups_by_event.items():
        groups = hooks.setdefault(event, [])
        for existing in groups:
            existing["hooks"] = [h for h in existing.get("hooks", []) if not _is_ours(h)]
        groups[:] = [existing for existing in groups if existing["hooks"]]
        groups.append(group)
    return settings


def _claude_hooks(command: list[str]) -> dict[str, dict]:
    return {
        "SessionStart": {"matcher": "startup|clear|compact", "hooks": [_brief_hook(command)]},
        "Stop": {"hooks": [_turn_hook(command, "claude", "stop")]},
        "UserPromptSubmit": {"hooks": [_turn_hook(command, "claude", "prompt")]},
    }


def _codex_hooks(command: list[str]) -> dict[str, dict]:
    return {
        "Stop": {"hooks": [_turn_hook(command, "codex", "stop")]},
        "UserPromptSubmit": {"hooks": [_turn_hook(command, "codex", "prompt")]},
    }


def _claude_server(command: list[str]) -> dict:
    """Claude Code tells the MCP server its session in CLAUDE_CODE_SESSION_ID. A Flatpak started
    from a container (distrobox runs `flatpak` on the host through host-spawn) arrives without
    the agent's environment, so a shell hands the id over as an argument, as the brief hook does
    with the folder. Without it Moah can't tell which task the person's reply in the chat
    answers, and the question waits in Review after it was answered."""
    args = [*command[1:], "--agent", "claude"]
    if command[0] != "flatpak":
        return {"type": "stdio", "command": command[0], "args": args, "env": {}}
    line = f'exec {shlex.join([command[0], *args, "--session-id"])} "${{CLAUDE_CODE_SESSION_ID:-}}"'
    return {"type": "stdio", "command": "sh", "args": ["-c", line], "env": {}}


def _claude_connected(data: dict) -> bool:
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return False
    return SERVER_NAME in servers or _ours(json.dumps(servers.get(OLD_SERVER_NAME, "")))


def _write_json_if_changed(path: Path, before: dict, after: dict) -> None:
    if after != before:
        _write(path, json.dumps(after, indent=2, ensure_ascii=False) + "\n")


def connect_claude(command: list[str], *, refresh: bool = False) -> bool:
    """False when Claude Code isn't on this computer, or, to refresh, isn't connected to Moah."""
    home = claude_home()
    custom_home = bool(os.environ.get("CLAUDE_CONFIG_DIR"))
    config = (home if custom_home else Path.home()) / ".claude.json"
    if not home.exists() and not config.exists():
        return False
    before = _read_json(config)
    if refresh and not _claude_connected(before):
        return False
    data = copy.deepcopy(before)
    servers = data.setdefault("mcpServers", {})
    if _ours(json.dumps(servers.get(OLD_SERVER_NAME, ""))):
        del servers[OLD_SERVER_NAME]
    entry = _claude_server(command)
    old = servers.get(SERVER_NAME)
    if isinstance(old, dict) and isinstance(old.get("env"), dict):
        entry["env"] = old["env"]  # variables a person added stay
    servers[SERVER_NAME] = entry
    settings_path = home / "settings.json"
    settings_before = _read_json(settings_path)
    settings = _with_hooks(copy.deepcopy(settings_before), _claude_hooks(command))
    # Claude Code rewrites its own file often: touch it only when something really changed.
    _write_json_if_changed(config, before, data)
    _write_json_if_changed(settings_path, settings_before, settings)
    return True


def _with_codex_server(config: str, command: list[str]) -> str:
    args = ", ".join(
        json.dumps(arg, ensure_ascii=False) for arg in [*command[1:], "--agent", "codex"]
    )
    section = (
        f"[mcp_servers.{SERVER_NAME}]\n"
        f"command = {json.dumps(command[0], ensure_ascii=False)}\n"
        f"args = [{args}]\n"
        "startup_timeout_sec = 20\n"
    )
    config = OLD_CODEX_SECTION.sub(lambda m: "" if _ours(m[0].split("\n", 1)[-1]) else m[0], config)
    if CODEX_SECTION.search(config):
        updated = CODEX_SECTION.sub(lambda _: section + "\n", config, count=1)
    else:
        updated = f"{config.rstrip()}\n\n{section}" if config.strip() else section
    tomllib.loads(updated)  # Never save a file Codex couldn't read.
    return updated


def _codex_connected(config: str) -> bool:
    if CODEX_SECTION.search(config):
        return True
    return any(_ours(m[0].split("\n", 1)[-1]) for m in OLD_CODEX_SECTION.finditer(config))


def _same_toml(before: str, after: str) -> bool:
    try:
        return tomllib.loads(before) == tomllib.loads(after)
    except tomllib.TOMLDecodeError:
        return False


def connect_codex(command: list[str], *, refresh: bool = False) -> bool:
    """False when Codex isn't on this computer, or, to refresh, isn't connected to Moah."""
    home = codex_home()
    if not home.exists():
        return False
    config_path = home / "config.toml"
    config = _read(config_path)
    if refresh and not _codex_connected(config):
        return False
    updated = _with_codex_server(config, command)
    if not _same_toml(config, updated):
        _write(config_path, updated)
    # Codex runs these only after the person trusts them once with /hooks (Help says so).
    hooks_path = home / "hooks.json"
    hooks_before = _read_json(hooks_path)
    hooks = _with_hooks(copy.deepcopy(hooks_before), _codex_hooks(command))
    _write_json_if_changed(hooks_path, hooks_before, hooks)
    if refresh:
        return True  # once connected, AGENTS.md is the person's to change
    agents_path = home / "AGENTS.md"
    agents = _read(agents_path)
    if "brain_brief" not in agents:
        _write(
            agents_path, f"{agents.rstrip()}\n\n{CODEX_BRIEF}" if agents.strip() else CODEX_BRIEF
        )
    return True


def connect_agents(launch: dict | None = None) -> list[dict]:
    """Connect every agent found here. Each result is connected, not_found or failed."""
    launch = launch or agent_launch()
    blocked = blocked_reason(launch)
    results = []
    for agent, connect in (("claude", connect_claude), ("codex", connect_codex)):
        if blocked:
            results.append({"agent": agent, "status": "failed", "detail": blocked})
            continue
        try:
            found = connect(launch["command"])
            results.append(
                {"agent": agent, "status": "connected" if found else "not_found", "detail": ""}
            )
        except (OSError, ValueError) as error:
            results.append({"agent": agent, "status": "failed", "detail": str(error)})
    return results


def refresh_connections(launch: dict | None = None) -> list[str]:
    """At the app's start, point the agents already connected to Moah at this install again.

    An update that changes how agents start Moah, or an install in another folder, then needs no
    Connect. Agents that were never connected stay untouched, and files are written only when
    something changed. Returns the connected agents. Never raises: a problem goes to the error
    log, and Connect in Help still works.
    """
    try:
        launch = launch or agent_launch()
        if blocked_reason(launch):
            return []  # the sandboxed Flatpak: its agents hear it from connection_notice
    except Exception as error:  # noqa: BLE001 - a background check must never stop the app
        error_log.write("service", f"Checking the agent connections: {error}")
        return []
    connected = []
    for agent, connect in (("claude", connect_claude), ("codex", connect_codex)):
        try:
            if connect(launch["command"], refresh=True):
                connected.append(agent)
        except Exception as error:  # noqa: BLE001 - as above
            error_log.write("service", f"Refreshing the {agent} connection: {error}")
    return connected


def connection_notice(agent: str, session_id: str | None) -> str | None:
    """What to tell an agent whose Flatpak connection was made before Connect passed on its
    session (Project Moah 0.3.0 and older), when that matters: Claude Code runs where its
    environment doesn't reach the Flatpak, such as a distrobox. Then the person's reply in the
    chat can't close the question it answers. None when the connection is fine.

    The sandboxed Flatpak can't rewrite the agent's settings itself, so the agent does, once.
    """
    if not FLATPAK_INFO.exists() or agent.strip().casefold() != "claude":
        return None
    if session_id is not None or os.environ.get(SESSION_ENV):
        return None  # a current connection, or the session arrived anyway
    return (
        "MOAH CONNECTION IS OUT OF DATE: this Claude Code connection to Project Moah was set up "
        "by an older version, so Moah doesn't get this session's id, and the person's answers in "
        "this chat can't close their questions in Review. Everything else works. Refresh it once "
        f"by running this command: {FLATPAK_CONNECT} . It takes effect in the next Claude Code "
        "session. It changes the agent's settings, so ask the person first and run it only "
        "when they agree; otherwise tell them this command once."
    )


def main() -> int:
    """`--connect`, for an agent or a person at a terminal. Exit 1 means a person is needed."""
    results = connect_agents()
    names = {"claude": "Claude Code", "codex": "Codex"}
    for result in results:
        name = names[result["agent"]]
        if result["status"] == "connected":
            print(f"{name}: connected. Restart it to load Project Moah.")
        elif result["status"] == "not_found":
            print(f"{name}: not found on this computer, skipped.")
        else:
            print(f"{name}: could not connect: {result['detail']}")
    failed = any(result["status"] == "failed" for result in results)
    # The sandboxed Flatpak's answer already is the command to run; Help would only repeat it.
    if failed and FLATPAK_CONNECT not in results[0]["detail"]:
        print("Open Project Moah and choose Connect on the Help page, or follow its manual steps.")
    if all(result["status"] == "not_found" for result in results):
        print("Install Claude Code or Codex, then run this again.")
        return 1
    return 1 if failed else 0

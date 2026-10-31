"""Connect Claude Code and Codex to this installation in one step.

Writes the same settings Help lists by hand. Other settings in those files are kept, a first
backup is saved next to each changed file, and running it again changes nothing new.
"""

from __future__ import annotations

import configparser
import json
import os
import re
import shlex
import shutil
import sys
import tomllib
from pathlib import Path

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
    os.replace(temporary, path)


def _read_json(path: Path) -> dict:
    text = _read(path).strip()
    data = json.loads(text) if text else {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a settings file")
    return data


def _brief_hook(command: list[str]) -> dict:
    # Claude Code runs hooks through a shell and has no "args" field. On Windows that shell is
    # cmd.exe or Git Bash, which spell "$VAR" differently, so the brief reads the folder itself.
    if sys.platform == "win32":
        line = " ".join(f'"{part}"' if " " in part else part for part in [*command, "--brief"])
        return {"type": "command", "command": line, "timeout": 20}
    line = f'{shlex.join([*command, "--brief", "--cwd"])} "$CLAUDE_PROJECT_DIR"'
    return {"type": "command", "command": line, "timeout": 20}


def _with_brief_hook(settings: dict, command: list[str]) -> dict:
    """Settings with exactly one Project Moah session hook, keeping every other hook."""
    groups = settings.setdefault("hooks", {}).setdefault("SessionStart", [])
    for group in groups:
        group["hooks"] = [hook for hook in group.get("hooks", []) if "--brief" not in str(hook)]
    groups[:] = [group for group in groups if group["hooks"]]
    groups.append({"matcher": "startup|clear|compact", "hooks": [_brief_hook(command)]})
    return settings


def connect_claude(command: list[str]) -> bool:
    """False when Claude Code isn't on this computer."""
    home = claude_home()
    custom_home = bool(os.environ.get("CLAUDE_CONFIG_DIR"))
    config = (home if custom_home else Path.home()) / ".claude.json"
    if not home.exists() and not config.exists():
        return False
    data = _read_json(config)
    servers = data.setdefault("mcpServers", {})
    if _ours(json.dumps(servers.get(OLD_SERVER_NAME, ""))):
        del servers[OLD_SERVER_NAME]
    servers[SERVER_NAME] = {
        "type": "stdio",
        "command": command[0],
        "args": [*command[1:], "--agent", "claude"],
        "env": {},
    }
    settings_path = home / "settings.json"
    settings = _with_brief_hook(_read_json(settings_path), command)
    _write(config, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    _write(settings_path, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
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


def connect_codex(command: list[str]) -> bool:
    """False when Codex isn't on this computer."""
    home = codex_home()
    if not home.exists():
        return False
    config_path = home / "config.toml"
    _write(config_path, _with_codex_server(_read(config_path), command))
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

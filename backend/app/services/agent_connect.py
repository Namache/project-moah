"""Connect Claude Code and Codex to this installation in one step.

Writes the same settings Help lists by hand. Other settings in those files are kept, a first
backup is saved next to each changed file, and running it again changes nothing new.

People connect once. After an update, the app refreshes the connections it finds when it starts
(`refresh_connections`). The sandboxed Flatpak can't change an agent's server entry, so it has Moah
tell the agent how (`connection_notice`); but the manifest gives it the two hook files themselves,
and there it refreshes Moah's hooks in place (`refresh_sandboxed_hooks`), so a change to the hooks
needs no command from the person.
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

from sqlalchemy.engine import make_url

from app.core import error_log
from app.core.config import get_database_url
from app.services.agent_sessions import SESSION_ENV
from app.services.codex_waiter import flatpak_stop_line
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
# The Moah tools whose calls the tool hook reports (services/hook_text.py MOAH_TOOL): the desktop
# app's own server is project-brain, the one Connect writes is project-moah.
TOOL_MATCHER = "mcp__project[-_](moah|brain)__brain_.*"
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


def data_folder() -> Path:
    """Moah's own data folder: the one that holds its database. Raises OSError when the database
    is not a file."""
    url = make_url(get_database_url())
    if not url.drivername.startswith("sqlite") or url.database in (None, "", ":memory:"):
        raise OSError("Project Moah has no data folder here")
    return Path(url.database).expanduser().resolve().parent


def _put_back(path: Path, old: bytes) -> bool:
    """Write the bytes a file had before an in-place write went wrong. True when it reads back."""
    try:
        with open(path, "rb+") as file:
            file.write(old)
            file.truncate()
            file.flush()
            os.fsync(file.fileno())
        return path.read_bytes() == old
    except OSError:
        return False


def _write_in_place(path: Path, text: str, expected: bytes, backup: Path) -> None:
    """Rewrite a file that can't be replaced, as the sandboxed Flatpak's hook files can't.

    The manifest gives the Flatpak that one file (a single-file bind mount) and not its folder.
    A mount point can't be renamed over (os.replace fails with "device or resource busy"), and
    the folder around it is the sandbox's own throwaway one, where the temp file and the
    ``.moah-backup`` that ``_write`` makes beside a file would land and be lost. So: the new text
    is validated first; the backup goes to Moah's own data folder, once (never overwritten, as
    with ``_write``); the file is opened r+ (keeping its permissions and owner), the new bytes
    are written and the rest of the old ones cut off (never an empty file in between), flushed,
    fsynced and read back. On any failure the bytes it had are put back and logged, and the error
    is raised for the caller to log. ``expected`` is what the new text was built from: when the
    file changed meanwhile (the agent writes its own settings), nothing is written.
    """
    json.loads(text)  # never save what the agent couldn't read
    new = text.encode("utf-8")
    touched = False
    try:
        with open(path, "rb+") as file:  # a file that can't be opened for writing is untouched
            if file.read() != expected:
                raise OSError(f"{path.name} changed while Moah read it; left for the next start")
            if not backup.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(expected)
            touched = True
            file.seek(0)
            file.write(new)
            file.truncate()
            file.flush()
            os.fsync(file.fileno())
        if path.read_bytes() != new:
            raise OSError(f"{path.name} did not read back as written")
    except Exception as error:  # noqa: BLE001 - whatever went wrong, the old text goes back
        if touched:
            restored = _put_back(path, expected)
            error_log.write(
                "service",
                f"Writing {path.name} in place failed ({error}); "
                + ("the old text is back." if restored else "the old text could not be put back."),
            )
        raise


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


def _hook(
    command: list[str],
    agent: str,
    hook: str,
    flags: tuple[str, ...] = (),
    *,
    timeout: int = 15,
    mode: dict | None = None,
) -> dict:
    """One hook of Project Moah's (services/chat_questions.py, chat_wait.py). ``mode`` is how
    Claude Code runs it: {"async": True} sends the event on without waiting, {"asyncRewake": True}
    runs it in the background and wakes the chat when it exits 2 (Claude Code enforces the
    timeout for asyncRewake, not for async). Codex runs every hook in turn: no mode."""
    line = _line([*command, "--agent", agent, "--hook", hook, *flags])
    return {"type": "command", "command": line, **(mode or {}), "timeout": timeout}


def _is_ours(hook: object) -> bool:
    """Whether an agent's hook is one of Project Moah's: it starts Moah and is the brief or a turn
    hook. A hook of the person's that happens to say --brief (git diff --brief) is not."""
    text = str(hook)
    return _ours(text) and ("--brief" in text or "--hook" in text)


def _has_our_hooks(settings: dict) -> bool:
    """Whether an agent's hook file holds any hook of Project Moah's: the agent was connected."""
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return False
    return any(
        _is_ours(hook)
        for groups in hooks.values()
        if isinstance(groups, list)
        for group in groups
        if isinstance(group, dict)
        for hook in group.get("hooks") or []
    )


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
    """Claude Code's hooks. Stop records the turn (after SETTLE seconds, so a message the person
    is already writing gets there first) and, side by side, waits for the person's answer in
    Review and wakes the chat with it; the prompt hook hands over what was not delivered; the tool
    hook learns the chat of every Moah tool call (chat_wait.py has the details)."""
    return {
        "SessionStart": {"matcher": "startup|clear|compact", "hooks": [_brief_hook(command)]},
        "Stop": {
            "hooks": [
                _hook(command, "claude", "stop", ("--settle",), timeout=60, mode={"async": True}),
                _hook(command, "claude", "wait", timeout=86400, mode={"asyncRewake": True}),
            ]
        },
        "UserPromptSubmit": {
            "hooks": [
                _hook(
                    command,
                    "claude",
                    "prompt",
                    ("--deliver",),
                    timeout=60,
                    mode={"asyncRewake": True},
                )
            ]
        },
        "PostToolUse": {
            "matcher": TOOL_MATCHER,
            "hooks": [_hook(command, "claude", "tool", timeout=30, mode={"async": True})],
        },
    }


def _flatpak(command: list[str]) -> bool:
    return command[0] == "flatpak"


def _codex_hooks(command: list[str]) -> dict[str, dict]:
    """Codex's hooks. Codex asks the person to trust a new or changed hook once, so a line that
    does not need to change stays exactly as it was: the Stop and prompt hooks of earlier
    versions. Stop starts the waiter that hands Review's answers to the session from Moah's own
    Python; the Flatpak cannot run ``codex``, so there its Stop line's shell does it
    (codex_waiter.flatpak_stop_line). The tool hook runs before Stop, so it is not async."""
    stop = _hook(command, "codex", "stop")
    if _flatpak(command):
        stop = {"type": "command", "command": flatpak_stop_line(command), "timeout": 15}
    return {
        "Stop": {"hooks": [stop]},
        "UserPromptSubmit": {"hooks": [_hook(command, "codex", "prompt")]},
        "PostToolUse": {
            "matcher": TOOL_MATCHER,
            "hooks": [_hook(command, "codex", "tool", timeout=30)],
        },
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


def _refresh_hooks_in_place(path: Path, hooks: dict[str, dict], backup: Path) -> bool:
    """Bring Moah's hooks in an agent's hook file up to date, in place. False (nothing touched)
    when the file isn't there or holds none of Moah's hooks: the agent was never connected."""
    if not path.is_file():
        return False
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    before = json.loads(text) if text.strip() else {}
    if not isinstance(before, dict) or not _has_our_hooks(before):
        return False
    after = _with_hooks(copy.deepcopy(before), hooks)
    if after != before:
        _write_in_place(path, json.dumps(after, indent=2, ensure_ascii=False) + "\n", raw, backup)
    return True


def refresh_sandboxed_hooks(command: list[str]) -> list[str]:
    """What the sandboxed Flatpak can do at the app's start: keep Moah's hooks current in the two
    files the manifest gives it (``~/.claude/settings.json``, ``~/.codex/hooks.json``).

    Only a file that already holds hooks of Moah's is touched: an agent that was never connected
    gets none, and nothing else is read or written (``~/.claude.json`` and ``config.toml`` are not
    visible here). A file the sandbox does not see (an installed app older than the grant, or no
    such file when the app started) is skipped, and the agent keeps the hooks it has. Returns the
    agents whose hooks were found. A failure goes to the error log.
    """
    backups = data_folder() / "agent-backups"
    found = []
    for agent, path, hooks in (
        ("claude", claude_home() / "settings.json", _claude_hooks(command)),
        ("codex", codex_home() / "hooks.json", _codex_hooks(command)),
    ):
        try:
            if _refresh_hooks_in_place(path, hooks, backups / f"{agent}-{path.name}.moah-backup"):
                found.append(agent)
        except Exception as error:  # noqa: BLE001 - a background check must never stop the app
            error_log.write("service", f"Refreshing the {agent} hooks: {error}")
    return found


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
    something changed. Returns the connected agents (in the sandboxed Flatpak: the agents whose
    hooks it found). Never raises: a problem goes to the error log, and Connect in Help still
    works.
    """
    try:
        launch = launch or agent_launch()
        if blocked_reason(launch):
            if launch["install"] == "flatpak":
                # The sandboxed Flatpak: its hooks only. The server entries are in files it
                # can't see, and its agents hear about those from connection_notice.
                return refresh_sandboxed_hooks(launch["command"])
            return []
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

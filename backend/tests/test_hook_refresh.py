"""The sandboxed Flatpak keeps Moah's hooks current in the two files its manifest shares with it.

Those are single-file grants: the file can be written, but not renamed over, and the folder around
it is the sandbox's own. So the hooks are rewritten in place, and the backup lives in Moah's data
folder. Nothing else of an agent's settings is read or written there.
"""

import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import NamedTuple

import pytest

from app.services import agent_connect
from app.services.codex_waiter import flatpak_stop_line

COMMAND = ["flatpak", "run", "--command=project-moah-mcp", "io.github.projectbrain.ProjectBrain"]
FP = " ".join(COMMAND)
LAUNCH = {"install": "flatpak", "command": COMMAND}
# The [Context] Flatpak writes for the app: the manifest's grants, no home folder.
SANDBOX = (
    "[Context]\nfilesystems=~/.claude/projects:ro;~/.codex/sessions:ro;"
    "~/.claude/settings.json;~/.codex/hooks.json;xdg-config/Claude/claude-code-sessions:ro;\n"
)
OWN_STOP = {"hooks": [{"type": "command", "command": "notify-send done"}]}
REPO = Path(__file__).resolve().parents[2]


class Box(NamedTuple):
    home: Path
    data: Path
    logged: list[str]

    @property
    def settings(self) -> Path:
        return self.home / ".claude/settings.json"

    @property
    def hooks(self) -> Path:
        return self.home / ".codex/hooks.json"


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Box:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".codex").mkdir()
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(agent_connect.sys, "platform", "linux")
    (tmp_path / "flatpak-info").write_text(SANDBOX)
    monkeypatch.setattr(agent_connect, "FLATPAK_INFO", tmp_path / "flatpak-info")
    data = tmp_path / "moah-data"  # a test never touches the real data folder
    monkeypatch.setattr(agent_connect, "data_folder", lambda: data)
    logged: list[str] = []
    monkeypatch.setattr(
        agent_connect.error_log, "write", lambda _source, message, *_, **__: logged.append(message)
    )
    return Box(home, data, logged)


def save(path: Path, data: dict) -> bytes:
    """Write the file and return its bytes. Bytes, not text: on Windows ``write_text`` would end
    the lines with CRLF, and the file would no longer be what the tests compare it with."""
    raw = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return raw


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def earlier_claude() -> dict:
    """What Project Moah 0.4.3 wrote for Claude Code in the Flatpak, and a hook of the person's."""
    brief = {"type": "command", "command": f'{FP} --brief --cwd "$CLAUDE_PROJECT_DIR"'}
    stop = {"type": "command", "command": f"{FP} --agent claude --hook stop", "timeout": 15}
    prompt = {**stop, "command": f"{FP} --agent claude --hook prompt", "async": True}
    return {
        "model": "x",
        "hooks": {
            "SessionStart": [
                {"matcher": "startup|clear|compact", "hooks": [{**brief, "timeout": 20}]}
            ],
            "Stop": [OWN_STOP, {"hooks": [stop]}],
            "UserPromptSubmit": [{"hooks": [prompt]}],
        },
    }


def earlier_codex() -> dict:
    stop = {"type": "command", "command": f"{FP} --agent codex --hook stop", "timeout": 15}
    prompt = {**stop, "command": f"{FP} --agent codex --hook prompt"}
    return {
        "description": "mine",
        "hooks": {
            "Stop": [OWN_STOP, {"hooks": [stop]}],
            "UserPromptSubmit": [{"hooks": [prompt]}],
        },
    }


def snapshot(folder: Path) -> dict[str, bytes]:
    return {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="the Flatpak (Linux only) is what this is for, and it asserts POSIX modes and a "
    "folder that cannot be written (0o640, 0o555), which Windows does not have",
)
def test_the_hooks_are_rewritten_in_place_where_the_folder_cannot_be_written(
    box: Box, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = save(box.settings, earlier_claude())
    box.settings.chmod(0o640)
    inode = box.settings.stat().st_ino

    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("a single-file grant can't be renamed over or copied beside")

    # The folder around the file is read-only, as in the sandbox. A superuser can write anyway,
    # so the calls a read-only folder would stop are refused as well.
    for owner, name in ((agent_connect.os, "replace"), (agent_connect.shutil, "copy2")):
        monkeypatch.setattr(owner, name, refuse)
    monkeypatch.setattr(agent_connect.shutil, "copymode", refuse)
    box.settings.parent.chmod(0o555)
    try:
        assert agent_connect.refresh_connections(LAUNCH) == ["claude"]
    finally:
        box.settings.parent.chmod(0o755)

    assert [p.name for p in box.settings.parent.iterdir()] == [
        "settings.json"
    ]  # no temp, no backup
    assert box.settings.stat().st_ino == inode  # the same file, written where it is
    assert stat.S_IMODE(box.settings.stat().st_mode) == 0o640
    new = load(box.settings)
    assert box.settings.read_bytes().endswith(b"\n") and new["model"] == "x"
    stop = new["hooks"]["Stop"]
    assert stop[0] == OWN_STOP and len(stop) == 2
    assert stop[1] == agent_connect._claude_hooks(COMMAND)["Stop"]
    assert set(new["hooks"]) == {"SessionStart", "Stop", "UserPromptSubmit", "PostToolUse"}
    assert all(len(groups) == 1 for e, groups in new["hooks"].items() if e != "Stop")
    # The backup is in Moah's own data folder, and nowhere else.
    backup = box.data / "agent-backups/claude-settings.json.moah-backup"
    assert backup.read_bytes() == original
    assert [p.name for p in box.data.iterdir()] == ["agent-backups"]
    assert box.logged == []


def test_a_refresh_with_nothing_to_change_writes_nothing_and_the_backup_stays_the_first(
    box: Box, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = save(box.settings, earlier_claude())
    assert agent_connect.refresh_connections(LAUNCH) == ["claude"]
    done = box.settings.read_bytes()
    stamp = box.settings.stat().st_mtime_ns

    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("nothing changed, so nothing is written")

    with monkeypatch.context() as spy:
        spy.setattr(agent_connect, "_write_in_place", refuse)
        assert agent_connect.refresh_connections(LAUNCH) == ["claude"]
    assert box.settings.read_bytes() == done and box.settings.stat().st_mtime_ns == stamp

    # Another change later (here: the hooks go back to the old set): the first backup is kept.
    save(box.settings, {**earlier_claude(), "theme": "dark"})
    assert agent_connect.refresh_connections(LAUNCH) == ["claude"]
    backup = box.data / "agent-backups/claude-settings.json.moah-backup"
    assert backup.read_bytes() == first


@pytest.mark.parametrize(
    ("fault", "said"),
    [("fsync", "the old text is back"), ("short", "the old text is back")],
)
def test_a_failed_write_puts_the_old_text_back_and_says_so(
    box: Box, monkeypatch: pytest.MonkeyPatch, fault: str, said: str
) -> None:
    original = save(box.settings, earlier_claude())
    really = os.fsync
    calls: list[int] = []

    def flaky(fd: int) -> None:
        calls.append(fd)
        if len(calls) == 1:  # the write; the put-back after it works
            if fault == "fsync":
                raise OSError(5, "Input/output error")
            os.ftruncate(fd, 5)  # the disk kept only the start of the file
        really(fd)

    monkeypatch.setattr(agent_connect.os, "fsync", flaky)
    assert agent_connect.refresh_connections(LAUNCH) == []
    assert box.settings.read_bytes() == original
    assert any(said in message for message in box.logged)
    assert any(m.startswith("Refreshing the claude hooks") for m in box.logged)
    backup = box.data / "agent-backups/claude-settings.json.moah-backup"
    assert backup.read_bytes() == original


def test_when_the_old_text_cannot_be_put_back_that_is_logged(
    box: Box, monkeypatch: pytest.MonkeyPatch
) -> None:
    save(box.settings, earlier_claude())

    def broken(_fd: int) -> None:
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(agent_connect.os, "fsync", broken)
    assert agent_connect.refresh_connections(LAUNCH) == []
    assert any("could not be put back" in message for message in box.logged)


def test_a_file_that_cannot_be_opened_for_writing_is_left_untouched(
    box: Box, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = save(box.settings, earlier_claude())
    import builtins

    def deny(file, mode="r", *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        if "+" in mode:
            raise PermissionError(13, "Permission denied")
        return builtins.open(file, mode, *args, **kwargs)

    monkeypatch.setattr(agent_connect, "open", deny, raising=False)
    assert agent_connect.refresh_connections(LAUNCH) == []
    assert box.settings.read_bytes() == original
    assert not box.data.exists()  # no backup of a change that never started
    assert len(box.logged) == 1 and box.logged[0].startswith("Refreshing the claude hooks")


def test_a_backup_that_cannot_be_made_stops_the_write(box: Box) -> None:
    original = save(box.settings, earlier_claude())
    box.data.write_text("a file where the data folder should be")
    assert agent_connect.refresh_connections(LAUNCH) == []
    assert box.settings.read_bytes() == original
    assert len(box.logged) == 1


def test_an_in_place_write_refuses_bad_text_and_a_file_that_changed_meanwhile(
    tmp_path: Path,
) -> None:
    path = tmp_path / "hooks.json"
    path.write_bytes(b'{"a": 1}\n')  # bytes: a text file would get CRLF line ends on Windows
    backup = tmp_path / "backups/hooks.json.moah-backup"
    with pytest.raises(ValueError):  # never save what the agent couldn't read
        agent_connect._write_in_place(path, "{ nope", b'{"a": 1}\n', backup)
    with pytest.raises(OSError, match="changed while Moah read it"):
        agent_connect._write_in_place(path, "{}\n", b'{"a": 2}\n', backup)
    assert path.read_text() == '{"a": 1}\n' and not backup.parent.exists()
    # A shorter text leaves none of the old file behind.
    agent_connect._write_in_place(path, "{}\n", b'{"a": 1}\n', backup)
    assert path.read_bytes() == b"{}\n" and backup.read_bytes() == b'{"a": 1}\n'


def test_the_sandbox_touches_only_files_that_already_have_moah_hooks(box: Box) -> None:
    """Hooks of the person's own (even one that says --brief) and the server entries Moah can't
    see from the sandbox anyway stay exactly as they are, and no backup is made."""
    own = {"type": "command", "command": "git diff --brief"}
    save(box.settings, {"hooks": {"SessionStart": [{"hooks": [own]}], "Stop": [OWN_STOP]}})
    save(
        box.hooks,
        {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x --hook stop"}]}]}},
    )
    (box.home / ".claude.json").write_text(
        json.dumps({"mcpServers": {"project-moah": {"command": "old.exe"}}})
    )
    (box.home / ".codex/config.toml").write_text(
        '[mcp_servers.project-moah]\ncommand = "old.exe"\n'
    )
    (box.home / ".codex/AGENTS.md").write_text("My notes.\n")
    before = snapshot(box.home)

    assert agent_connect.refresh_connections(LAUNCH) == []
    assert snapshot(box.home) == before
    assert not box.data.exists() and box.logged == []


@pytest.mark.parametrize(
    "text",
    [
        "",
        "{}",
        '{"hooks": []}',
        '{"hooks": {"Stop": "x"}}',
        '{"hooks": {"Stop": [1, {"hooks": null}, {"hooks": [{"command": "other"}]}]}}',
    ],
)
def test_an_agent_that_was_never_connected_gets_no_hooks(box: Box, text: str) -> None:
    assert agent_connect.refresh_connections(LAUNCH) == []  # no hook files at all
    assert not box.settings.exists() and not box.hooks.exists()
    box.settings.write_text(text)
    box.hooks.write_text(text)
    assert agent_connect.refresh_connections(LAUNCH) == []
    assert box.settings.read_text() == text and box.hooks.read_text() == text
    assert not box.data.exists() and box.logged == []


def test_the_sandbox_brings_both_agents_up_to_date_and_keeps_the_persons_hooks(box: Box) -> None:
    claude = save(box.settings, earlier_claude())
    codex = save(box.hooks, earlier_codex())

    assert agent_connect.refresh_connections(LAUNCH) == ["claude", "codex"]

    new = load(box.settings)["hooks"]
    assert new["Stop"][0] == OWN_STOP and len(new["Stop"]) == 2
    assert new["PostToolUse"] == [agent_connect._claude_hooks(COMMAND)["PostToolUse"]]
    hooks = load(box.hooks)
    assert hooks["description"] == "mine"
    stop = hooks["hooks"]["Stop"]
    assert stop[0] == OWN_STOP and len(stop) == 2
    assert stop[1]["hooks"][0]["command"] == flatpak_stop_line(COMMAND)  # the line that waits
    # The prompt hook is the line Codex already trusts, byte for byte.
    dumps = json.dumps
    assert dumps(hooks["hooks"]["UserPromptSubmit"], indent=2) == dumps(
        earlier_codex()["hooks"]["UserPromptSubmit"], indent=2
    )
    assert (
        hooks["hooks"]["PostToolUse"][0]["hooks"][0]["command"] == f"{FP} --agent codex --hook tool"
    )
    backups = box.data / "agent-backups"
    assert (backups / "claude-settings.json.moah-backup").read_bytes() == claude
    assert (backups / "codex-hooks.json.moah-backup").read_bytes() == codex
    assert box.logged == []


def test_one_agents_failure_does_not_stop_the_other(box: Box) -> None:
    box.settings.write_text("{ not json")
    save(box.hooks, earlier_codex())
    assert agent_connect.refresh_connections(LAUNCH) == ["codex"]
    assert box.settings.read_text() == "{ not json"
    assert len(box.logged) == 1 and box.logged[0].startswith("Refreshing the claude hooks")
    assert "PostToolUse" in load(box.hooks)["hooks"]


def test_a_missing_hook_file_is_skipped_without_a_word(box: Box) -> None:
    """The grant of a single file binds it only if it exists when the app starts."""
    save(box.hooks, earlier_codex())
    assert agent_connect.refresh_connections(LAUNCH) == ["codex"]
    assert box.logged == []


def test_a_flatpak_with_home_access_refreshes_everything_like_any_other_install(
    box: Box, tmp_path: Path
) -> None:
    (tmp_path / "flatpak-info").write_text("[Context]\nfilesystems=home;\n")
    old = {"project-moah": {"type": "stdio", "command": "old.exe", "args": [], "env": {}}}
    (box.home / ".claude.json").write_text(json.dumps({"mcpServers": old}))
    save(box.settings, earlier_claude())

    assert agent_connect.refresh_connections(LAUNCH) == ["claude"]

    server = load(box.home / ".claude.json")["mcpServers"]["project-moah"]
    assert server["command"] == "sh"  # the server entry too, which the sandbox can't see
    assert "PostToolUse" in load(box.settings)["hooks"]
    assert (box.settings.parent / "settings.json.moah-backup").exists()  # beside the file, as ever
    assert not box.data.exists()


def test_the_data_folder_is_the_one_that_holds_the_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PROJECT_BRAIN_DATABASE_URL", raising=False)
    monkeypatch.setenv("PROJECT_BRAIN_DB_PATH", str(tmp_path / "moah/project-brain.db"))
    assert agent_connect.data_folder() == (tmp_path / "moah").resolve()
    monkeypatch.setenv("PROJECT_BRAIN_DATABASE_URL", "sqlite:///:memory:")
    with pytest.raises(OSError):
        agent_connect.data_folder()


def manifest_grants(text: str) -> list[str]:
    block = re.search(r"^finish-args:\n((?:  .*\n|\n)+)", text, re.MULTILINE)
    assert block, "the manifest has no finish-args"
    args = re.findall(r"^  - (\S+)\s*$", block[1], re.MULTILINE)  # comments don't start with "- "
    return [arg for arg in args if arg.startswith("--filesystem=")]


GRANTS = [
    "--filesystem=~/.claude/projects:ro",
    "--filesystem=~/.codex/sessions:ro",
    "--filesystem=~/.claude/settings.json",
    "--filesystem=~/.codex/hooks.json",
    "--filesystem=xdg-config/Claude/claude-code-sessions:ro",
]


def test_the_manifest_shares_exactly_the_hook_files_and_the_chat_records() -> None:
    """Moah's hooks, and Review's way to the chat, need exactly these and no home folder, no
    folder of agent settings, and nothing read-write but the two single files."""
    manifest = REPO / "desktop/io.github.projectbrain.ProjectBrain.yml"
    script = REPO / "scripts/build-flatpak.sh"
    if not manifest.exists() or not script.exists():
        pytest.skip("the packaging files are not part of this checkout")
    assert manifest_grants(manifest.read_text(encoding="utf-8")) == GRANTS
    # The release is built with `flatpak build-finish`, which has its own copy of the list.
    assert re.findall(r"--filesystem=\S+", script.read_text(encoding="utf-8")) == GRANTS
    # Read and write: those two single files, nothing else.
    assert [g for g in GRANTS if not g.endswith(":ro")] == [
        "--filesystem=~/.claude/settings.json",
        "--filesystem=~/.codex/hooks.json",
    ]

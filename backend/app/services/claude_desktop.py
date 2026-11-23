"""Find the Claude desktop app's own record of a Claude Code chat.

Claude Code names a chat by its session id, but the desktop app opens a chat by its own id (a
``local_<uuid>`` record). The app keeps one JSON file per chat under its config folder:
``claude-code-sessions/<account>/<organisation>/local_<uuid>.json``. A file says which Claude Code
session it runs (``cliSessionId``, and ``lastAssistantCliSessionId`` once a /clear or a resume
started another), and whether the person archived it. Reading these files is the only way to go
from a session id to the link ``claude://code/continue?session=<local id>``.

The folder is the app's, not Moah's: nothing here writes to it, follows a link out of it, or keeps
more than the id of the record found. Standard library only, so it stays cheap to import and safe
to use from anywhere. Linux and macOS paths are the app's usual places; the Windows path
(``%APPDATA%\\Claude``) is a guess nobody has checked on a Windows machine.

Reading is bounded, because a long-time user has hundreds of records of several hundred kilobytes:
only files changed in the last MAX_AGE_DAYS, the newest MAX_FILES of them, newest first, each
looked at as raw bytes for the session id before it is parsed, stopping at the first match.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

FOLDER = "claude-code-sessions"
RECORD_ID = re.compile(r"^local_[A-Za-z0-9-]{1,64}$")
SESSION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")  # as hook_text.valid_id
MAX_DEPTH = 3  # folders below claude-code-sessions
MAX_AGE_DAYS = 30
MAX_FILES = 120
MAX_BYTES = 32 << 20  # a record is a few hundred kilobytes; one this big is not one

FOUND = "found"
NOT_FOUND = "not_found"  # the records were read and none is this chat's: it runs elsewhere
UNREADABLE = "unreadable"  # the folder is missing or not allowed to be read: nothing is known


@dataclass(frozen=True)
class Lookup:
    """What the search found. ``record`` is the app's ``local_<uuid>`` id, only when FOUND."""

    state: str
    record: str | None = None


def config_folders(
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
    home: Path | None = None,
) -> list[Path]:
    """The folders the desktop app keeps its data in on this machine, most likely first.

    Inside a Flatpak, XDG_CONFIG_HOME points into ~/.var/app/<id>/config, which is not the app's
    folder, so ~/.config is always looked at too (Path.home() is the real home there)."""
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    home = Path.home() if home is None else home
    if platform == "darwin":
        found = [home / "Library" / "Application Support" / "Claude"]
    elif platform.startswith("win"):
        appdata = environ.get("APPDATA")
        found = [Path(appdata) / "Claude" if appdata else home / "AppData" / "Roaming" / "Claude"]
    else:
        found = [home / ".config" / "Claude"]
        configured = environ.get("XDG_CONFIG_HOME")
        if configured and Path(configured).is_absolute():
            found.append(Path(configured) / "Claude")
    unique: list[Path] = []
    for folder in found:
        if folder not in unique:
            unique.append(folder)
    return unique


def _records(
    top: Path, cutoff: float | None, name: str | None = None
) -> tuple[list[tuple[float, Path]], bool]:
    """(modified time, path) of the record files under ``top`` (changed since ``cutoff``, or the
    one named ``name``), and whether anything below ``top`` could not be listed. Raises OSError
    when ``top`` itself cannot be. Symbolic links are not followed: the app does not make them,
    and a link could lead anywhere."""
    found: list[tuple[float, Path]] = []
    denied = False
    pending: list[tuple[Path, int]] = [(top, 0)]
    while pending:
        folder, depth = pending.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if depth < MAX_DEPTH:
                                pending.append((Path(entry.path), depth + 1))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        if name is not None:
                            if entry.name != name:
                                continue
                        elif not (entry.name.startswith("local_") and entry.name.endswith(".json")):
                            continue
                        changed = entry.stat(follow_symlinks=False).st_mtime
                    except OSError:
                        denied = True
                        continue
                    if cutoff is None or changed >= cutoff:
                        found.append((changed, Path(entry.path)))
        except OSError as error:
            if folder == top:
                raise
            # A folder below that vanished between its parent's listing and now: the app moves
            # records around, and nothing is lost. Any other failure means a part was not seen.
            denied = denied or not isinstance(error, FileNotFoundError)
    return found, denied


def _matches(data: bytes, session_id: str) -> str | None:
    """The record's id when this file is the live (not archived) record of the session."""
    try:
        record = json.loads(data)
    except ValueError:
        return None
    if not isinstance(record, dict) or record.get("isArchived"):
        return None
    local = record.get("sessionId")
    if not isinstance(local, str) or not RECORD_ID.match(local):
        return None
    if session_id in (record.get("cliSessionId"), record.get("lastAssistantCliSessionId")):
        return local
    return None


def _read(path: Path) -> bytes | None:
    """The file's bytes, or None when it is too big or vanished. A file that may not be read
    raises PermissionError, so the caller can tell that from the others."""
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        return path.read_bytes()
    except PermissionError:
        raise
    except OSError:
        return None


def find(
    session_id: str,
    folders: Sequence[Path] | None = None,
    now: datetime | None = None,
) -> Lookup:
    """The desktop app's record of the Claude Code session, as FOUND, NOT_FOUND (the records
    were readable and none is this chat's) or UNREADABLE (no folder to read, or none allowed).

    A record a person archived never matches: the app would not open it."""
    if not SESSION_ID.match(session_id or ""):
        return Lookup(NOT_FOUND)
    now = now or datetime.now(UTC)
    cutoff = (now - timedelta(days=MAX_AGE_DAYS)).timestamp()
    needle = session_id.encode()
    readable = False
    trouble = False  # something could not be read: the answer may be wrong either way
    for config in config_folders() if folders is None else folders:
        try:
            files, denied = _records(config / FOLDER, cutoff)
        except FileNotFoundError:
            readable = readable or config.is_dir()  # the app is there, with no Code chat yet
            continue
        except OSError:
            trouble = True
            continue
        readable = True
        trouble = trouble or denied
        files.sort(key=lambda item: item[0], reverse=True)
        for _, path in files[:MAX_FILES]:
            try:
                data = _read(path)
            except PermissionError:
                trouble = True
                continue
            if data is None or needle not in data:
                continue
            local = _matches(data, session_id)
            if local is not None:
                return Lookup(FOUND, local)
    return Lookup(NOT_FOUND if readable and not trouble else UNREADABLE)


def still_matches(record: str, session_id: str, folders: Sequence[Path] | None = None) -> bool:
    """Whether the app still has this record, not archived, for this session: what a stored
    answer of ``find`` needs before it is used again. Looks only at the file named after the
    record (the app names each file by its id), however old it is."""
    if not RECORD_ID.match(record or "") or not SESSION_ID.match(session_id or ""):
        return False
    for config in config_folders() if folders is None else folders:
        try:
            files, _ = _records(config / FOLDER, None, f"{record}.json")
        except OSError:
            continue
        for _, path in files:
            try:
                data = _read(path)
            except PermissionError:
                continue
            if data is not None and _matches(data, session_id) == record:
                return True
    return False

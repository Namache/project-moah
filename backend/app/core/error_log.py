"""A small local error log, so a person can see what went wrong without a terminal.

Each process writes its own file in a `logs` folder next to the database: the app's local service
writes `errors-service.log`, every MCP server writes `errors-mcp.log`, the desktop app writes its
own file in its settings folder, and Settings > Diagnostics reads them all. Nothing here goes
online. Files are JSON lines, kept small: past MAX_BYTES a file is moved to `<name>.1`, replacing
the older one, so the log never takes more than about a megabyte.

Only unexpected errors are written: a tool call an agent got wrong is the agent's answer, not an
error of the app. Messages are cleaned before they are saved: the home folder becomes `~` and the
values SQLAlchemy prints after a failed statement are dropped, since those can be record text.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

from app.core.config import get_database_url

MAX_BYTES = 256 * 1024
MAX_MESSAGE = 2_000
MAX_DETAIL = 12_000
READ_LIMIT = 200
SOURCES = ("service", "mcp", "desktop", "window")
# Electron passes the path of its own error file, so the service can show and clear it too.
DESKTOP_LOG_ENV = "PROJECT_BRAIN_DESKTOP_ERROR_LOG"
DIR_ENV = "PROJECT_BRAIN_ERROR_LOG_DIR"
_PARAMETERS = re.compile(r"\[parameters: .*?\](?=\n|$)", re.DOTALL)
_lock = threading.Lock()


def log_dir(database_url: str | None = None) -> Path | None:
    """The `logs` folder beside the database, or None when the database is not a file."""
    if explicit := os.getenv(DIR_ENV):
        return Path(explicit).expanduser()
    url = make_url(database_url or get_database_url())
    if not url.drivername.startswith("sqlite") or url.database in (None, "", ":memory:"):
        return None
    return Path(url.database).expanduser().resolve().parent / "logs"


def _files(database_url: str | None = None) -> list[Path]:
    found: list[Path] = []
    if (folder := log_dir(database_url)) is not None:
        for source in ("service", "mcp", "window"):
            found += [folder / f"errors-{source}.log", folder / f"errors-{source}.log.1"]
    if desktop := os.getenv(DESKTOP_LOG_ENV):
        found += [Path(desktop), Path(f"{desktop}.1")]
    return found


def hide_home(text: str) -> str:
    """Write the home folder as ~, so a copied report does not show the user name.

    The folder turns up spelled several ways: with forward slashes on Windows (database URLs),
    in any letter case there, and as /var/home/... on Fedora Atomic systems such as Bazzite.
    """
    home = str(Path.home())
    if len(home) <= 1:
        return text
    spellings = {home, home.replace("\\", "/")}
    if home.startswith("/home/"):
        spellings.add(f"/var{home}")
    elif home.startswith("/var/home/"):
        spellings.add(home.removeprefix("/var"))
    flags = re.IGNORECASE if sys.platform == "win32" else 0
    # Longest first, so /var/home/name is not left as /var~. Never inside a longer name.
    names = "|".join(re.escape(s) for s in sorted(spellings, key=len, reverse=True))
    return re.sub(rf"(?:{names})(?![^\\/\s\"':;,)\]])", "~", text, flags=flags)


def clean(text: str, limit: int) -> str:
    """Drop statement values, shorten the home folder, and cap the length."""
    text = hide_home(_PARAMETERS.sub("[parameters hidden]", text))
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def write(
    source: str,
    message: str,
    detail: str = "",
    *,
    level: str = "error",
    database_url: str | None = None,
) -> None:
    """Append one entry. Never raises: a broken log must not break the app."""
    try:
        folder = log_dir(database_url)
        if folder is None or source not in SOURCES or source == "desktop":
            return
        entry = {
            "time": datetime.now(UTC).isoformat(timespec="seconds"),
            "source": source,
            "level": level if level in ("error", "warning") else "error",
            "message": clean(message.strip() or "Unknown error", MAX_MESSAGE),
            "detail": clean(detail.strip(), MAX_DETAIL),
        }
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        path = folder / f"errors-{source}.log"
        with _lock:
            folder.mkdir(parents=True, exist_ok=True)
            try:
                if path.stat().st_size + len(line) > MAX_BYTES:
                    os.replace(path, path.with_name(path.name + ".1"))
            except OSError:
                pass  # no file yet, or another process is rotating it right now
            # One short append per entry: several MCP servers can share the file.
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line)
    except Exception:  # noqa: BLE001
        pass


def read(limit: int = READ_LIMIT, database_url: str | None = None) -> dict[str, Any]:
    """The newest entries from every source, newest first, and how many there are in all."""
    entries: list[dict[str, Any]] = []
    for path in _files(database_url):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if (
                isinstance(item, dict)
                and isinstance(item.get("time"), str)
                and item.get("source") in SOURCES
            ):
                entries.append(
                    {
                        "time": item["time"],
                        "source": item["source"],
                        "level": item.get("level")
                        if item.get("level") in ("error", "warning")
                        else "error",
                        "message": clean(str(item.get("message", "")), MAX_MESSAGE),
                        "detail": clean(str(item.get("detail", "")), MAX_DETAIL),
                    }
                )
    entries.sort(key=lambda item: item["time"], reverse=True)
    return {"total": len(entries), "entries": entries[:limit]}


def clear(database_url: str | None = None) -> None:
    for path in _files(database_url):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


class ErrorLogHandler(logging.Handler):
    """Sends ERROR records from Python's logging to the error log."""

    def __init__(self, source: str) -> None:
        super().__init__(level=logging.ERROR)
        self.source = source

    def emit(self, record: logging.LogRecord) -> None:
        # The same record can reach this handler from two loggers; write it once.
        if getattr(record, "_moah_error_logged", False):
            return
        record._moah_error_logged = True  # type: ignore[attr-defined]
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001
            message = str(record.msg)
        detail = "".join(traceback.format_exception(*record.exc_info)) if record.exc_info else ""
        write(
            self.source, f"{record.name}: {message}" if record.name != "root" else message, detail
        )


def install(source: str) -> None:
    """Route this process's unexpected errors to the log. Safe to call more than once."""
    handler = next(
        (h for h in logging.getLogger().handlers if isinstance(h, ErrorLogHandler)), None
    )
    if handler is None:
        handler = ErrorLogHandler(source)
        logging.getLogger().addHandler(handler)
        # uvicorn's own loggers do not pass records up to the root logger.
        logging.getLogger("uvicorn.error").addHandler(handler)
    handler.source = source
    previous = sys.excepthook
    previous_thread = threading.excepthook

    def excepthook(kind, value, tb) -> None:  # noqa: ANN001
        if not issubclass(kind, KeyboardInterrupt):
            write(
                source,
                f"{kind.__name__}: {value}",
                "".join(traceback.format_exception(kind, value, tb)),
            )
        previous(kind, value, tb)

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is not SystemExit and args.exc_value is not None:
            write(
                source,
                f"{args.exc_type.__name__} in thread {getattr(args.thread, 'name', '?')}: "
                f"{args.exc_value}",
                "".join(
                    traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
                ),
            )
        previous_thread(args)

    sys.excepthook = excepthook
    threading.excepthook = thread_hook

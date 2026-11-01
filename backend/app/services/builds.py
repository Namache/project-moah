"""Which build of Project Moah this process runs, and whether a newer one has been installed.

Agents start the MCP server once per session and keep it running, so after an update the old
process carries on serving packs from the old code. Each process therefore notes its build when
it starts, and an MCP process that sees a newer build tells its agent, once, to restart.

Everything stays on this computer. Two local signals say a newer build is installed:
- The shared database: every process records its build when it starts. The desktop app records
  its own as the installed one (it is what the person opened); MCP processes only ever raise it.
- The running executable changed on disk (Windows and .deb replace it in place). Flatpak keeps
  the old files mounted for a running sandbox, so there the database signal does the work: the
  restarted app, or any new agent session, records the new build.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.resources import resource_path
from app.models.app_setting import AppSetting
from app.models.graph import RetrievalSession
from app.services.system import APP_VERSION

INSTALLED = "installed_build"
# Written by scripts/build-backend-sidecar.py and bundled beside the code.
BUILD_INFO = "backend/build_info.json"


@dataclass(frozen=True)
class Build:
    version: str
    stamp: int  # seconds since the epoch the build was made; higher is newer
    commit: str | None = None

    @property
    def label(self) -> str:
        when = datetime.fromtimestamp(self.stamp, UTC).strftime("%Y%m%d.%H%M")
        return f"{self.version}+{when}" + (f".{self.commit}" if self.commit else "")

    def as_dict(self) -> dict:
        return {"version": self.version, "stamp": self.stamp, "commit": self.commit}

    @classmethod
    def from_dict(cls, value: object) -> Build | None:
        if not isinstance(value, dict) or not isinstance(value.get("stamp"), int | float):
            return None
        return cls(str(value.get("version") or "?"), int(value["stamp"]), value.get("commit"))


def _source_stamp() -> int:
    """Running from source: the newest code file's time, so an edit counts as a new build."""
    package = Path(__file__).resolve().parents[1]
    return int(max((p.stat().st_mtime for p in package.rglob("*.py")), default=0))


def detect_build() -> Build:
    try:
        info = json.loads(resource_path(BUILD_INFO).read_text(encoding="utf-8"))
        found = Build.from_dict({"version": APP_VERSION, **info})
        if found is not None:
            return found
    except (OSError, ValueError):
        pass
    return Build(APP_VERSION, _source_stamp())


_current: Build | None = None


def current_build() -> Build:
    global _current
    if _current is None:
        _current = detect_build()
    return _current


def installed_build(session: Session) -> Build | None:
    row = session.get(AppSetting, INSTALLED)
    return Build.from_dict(row.value) if row else None


def register_build(session: Session, build: Build | None = None, *, installed: bool) -> None:
    """Note this process's build. installed=True (the desktop app) sets it outright, so going
    back to an older version is not mistaken for an update; otherwise it is only ever raised."""
    build = build or current_build()
    row = session.get(AppSetting, INSTALLED)
    known = Build.from_dict(row.value) if row else None
    if known == build or (not installed and known is not None and known.stamp >= build.stamp):
        return
    row = row or AppSetting(key=INSTALLED)
    row.value, row.updated_at = build.as_dict(), datetime.now(UTC)
    session.add(row)
    session.commit()


def restart_notice(build: Build, newer: Build) -> str:
    return (
        f"MOAH WAS UPDATED: this session's Project Moah tools run build {build.label}, but "
        f"{newer.label} is installed now. Tell the person in one sentence that Project Moah was "
        "updated and this session should be restarted to use the new build, then carry on. "
        "Say it once."
    )


class UpdateWatch:
    """One MCP process's view: tells its agent about a newer build once, then stays quiet."""

    def __init__(self, build: Build | None = None, executable: str | None = None) -> None:
        self.build = build or current_build()
        self.told = False
        self.executable = Path(executable or sys.executable)
        self._exe_mtime = self._mtime()

    def _mtime(self) -> float | None:
        if not getattr(sys, "frozen", False) and self.executable == Path(sys.executable):
            return None  # from source, sys.executable is Python, not Moah
        try:
            return self.executable.stat().st_mtime
        except OSError:
            return None

    def newer(self, session: Session) -> Build | None:
        known = installed_build(session)
        if known is not None and known.stamp > self.build.stamp:
            return known
        mtime = self._mtime()
        if self._exe_mtime is not None and mtime is not None and mtime != self._exe_mtime:
            # Replaced in place; its own build is unknown until it runs, so say only that.
            return Build("a newer build", int(mtime))
        return None

    def notice(self, session: Session) -> str | None:
        """The restart notice the first time a newer build is seen, else None. Never raises."""
        if self.told:
            return None
        try:
            newer = self.newer(session)
        except Exception:  # noqa: BLE001 - a busy database must never cost the agent its answer
            session.rollback()
            return None
        if newer is None:
            return None
        self.told = True
        if newer.version == "a newer build":
            return (
                f"MOAH WAS UPDATED: this session's Project Moah tools run build "
                f"{self.build.label}, and a newer build has been installed since. Tell the person "
                "in one sentence that Project Moah was updated and this session should be "
                "restarted to use the new build, then carry on. Say it once."
            )
        return restart_notice(self.build, newer)


def pack_builds(session: Session, *, hours: int = 24) -> dict:
    """Packs served in the last day, by build, and how many came from an older build than the
    installed one. After an install this should fall to zero as agents restart."""
    since = datetime.now(UTC) - timedelta(hours=hours)
    rows = session.execute(
        select(RetrievalSession.build, func.count())
        .where(RetrievalSession.created_at >= since)
        .group_by(RetrievalSession.build)
    ).all()
    row = session.get(AppSetting, INSTALLED)
    installed = (Build.from_dict(row.value) if row else None) or current_build()
    by_build = {(build or "unknown"): n for build, n in rows}
    old = sum(n for build, n in rows if build is not None and build != installed.label)
    if row is not None:
        # Builds from before packs recorded their build leave it empty; any such pack served
        # after this build was installed came from an old process.
        after = max(since, _aware(row.updated_at))
        old += (
            session.scalar(
                select(func.count())
                .select_from(RetrievalSession)
                .where(RetrievalSession.build.is_(None), RetrievalSession.created_at >= after)
            )
            or 0
        )
    return {"installed": installed.label, "last_day": by_build, "old_build_last_day": old}


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)

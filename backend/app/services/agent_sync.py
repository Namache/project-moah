"""Sync from agents: find the folders Claude Code and Codex sessions start in, and give each real
project folder a Project Moah project without anyone choosing directories by hand.

Rules:
- Only the folder a session started in is read (the first lines of each log), never message text.
- Temporary and scratch folders, worktrees (counted under their repository) and Codex's one-off chat
  folders are skipped. A folder inside another found folder belongs to the outer one.
- A folder inside an existing project's folder is already covered.
- Nothing is guessed: when an existing project without a folder has a similar name, a person is
  asked to confirm the match. Otherwise a new project is created, named after the folder.
- A decision is remembered, so an ignored or archived folder is never brought back.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.agent_folder import AgentFolder
from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.services.activity import acting_as
from app.services.projects import ProjectService, name_key
from app.services.usage import claude_home, codex_home, normalize_folder

SYNC_ACTOR = "Sync from agents"
HEAD_LINES = 40
ONE_OFF_CODEX = re.compile(r"/Documents/Codex/\d{4}-\d{2}-\d{2}(/|$)")


@dataclass
class Sighting:
    claude: int = 0
    codex: int = 0
    first: datetime | None = None
    last: datetime | None = None

    def add(self, agent: str, at: datetime | None) -> None:
        setattr(self, agent, getattr(self, agent) + 1)
        if at is not None:
            self.first = at if self.first is None or at < self.first else self.first
            self.last = at if self.last is None or at > self.last else self.last


@dataclass
class _Cache:
    files: dict[Path, tuple[float, int, str | None, datetime | None]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


_cache = _Cache()


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _start_folder(agent: str, path: Path) -> tuple[str | None, datetime | None]:
    """The folder a session started in, from the first lines of its log."""
    try:
        with path.open("rb") as handle:
            for _ in range(HEAD_LINES):
                raw = handle.readline()
                if not raw:
                    break
                if agent == "claude" and b'"cwd"' in raw:
                    record = json.loads(raw)
                    return record.get("cwd"), _timestamp(record.get("timestamp"))
                if agent == "codex" and b'"session_meta"' in raw:
                    record = json.loads(raw)
                    payload = record.get("payload") or {}
                    return payload.get("cwd"), _timestamp(record.get("timestamp"))
    except (OSError, ValueError):
        pass
    return None, None


def session_folders(
    claude_dir: Path | None = None, codex_dir: Path | None = None
) -> dict[str, Sighting]:
    """Every folder a Claude Code or Codex session started in, with counts. Cached per file."""
    roots = {
        # Top-level session logs only; subagent logs repeat their parent's folder.
        "claude": sorted(((claude_dir or claude_home()) / "projects").glob("*/*.jsonl")),
        "codex": sorted(((codex_dir or codex_home()) / "sessions").rglob("*.jsonl")),
    }
    found: dict[str, Sighting] = {}
    with _cache.lock:
        for agent, paths in roots.items():
            for path in paths:
                try:
                    stat = path.stat()
                except OSError:
                    continue
                cached = _cache.files.get(path)
                if cached is None or cached[:2] != (stat.st_mtime, stat.st_size):
                    folder, at = _start_folder(agent, path)
                    cached = _cache.files[path] = (stat.st_mtime, stat.st_size, folder, at)
                folder, at = cached[2], cached[3]
                if isinstance(folder, str) and folder:
                    found.setdefault(normalize_folder(folder), Sighting()).add(agent, at)
    return found


def project_folder(folder: str) -> str | None:
    """The project folder a session folder stands for, or None when it is not a project."""
    home = normalize_folder(str(Path.home()))
    if not folder.startswith("/") or folder in ("/", home):
        return None
    for marker in ("/.claude/worktrees/", "/.codex/worktrees/"):
        if marker in folder + "/":
            folder = folder.split(marker.rstrip("/"))[0]
    skipped = (
        "/tmp",
        "/var/tmp",
        "/run",
        "/proc",
        f"{home}/.claude",
        f"{home}/.codex",
        f"{home}/.cache",
        f"{home}/.var",
        f"{home}/.config",
        f"{home}/.local",
    )
    if any(folder == root or folder.startswith(root + "/") for root in skipped):
        return None
    if ONE_OFF_CODEX.search(folder):
        return None
    return folder if folder not in ("/", home) else None


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def _similar_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name_key(name))


def _similar(folder_name: str, project_name: str) -> bool:
    a, b = _similar_key(folder_name), _similar_key(project_name)
    if not a or not b:
        return False
    short, long = sorted((a, b), key=len)
    return a == b or (len(short) >= 5 and long.startswith(short))


def sync_agent_folders(session: Session, sightings: dict[str, Sighting] | None = None) -> dict:
    """Bring projects in line with the agents' folders. Safe to run often and concurrently."""
    sightings = session_folders() if sightings is None else sightings
    now = datetime.now(UTC)
    # Collapse each session folder to its project folder, then nested folders into the outermost.
    projects = list(session.scalars(select(Project).where(Project.kind == "project")))
    roots = [(p, normalize_folder(p.root_path)) for p in projects if p.root_path]
    grouped: dict[str, Sighting] = {}
    for folder, seen in sightings.items():
        target = project_folder(folder)
        if target is None:
            continue
        # Work inside an existing project's folder counts toward that folder.
        target = next((root for _, root in roots if _inside(target, root)), target)
        merged = grouped.setdefault(target, Sighting())
        merged.claude += seen.claude
        merged.codex += seen.codex
        for at in (seen.first, seen.last):
            if at is not None:
                merged.first = at if merged.first is None or at < merged.first else merged.first
                merged.last = at if merged.last is None or at > merged.last else merged.last
    known = {row.folder: row for row in session.scalars(select(AgentFolder))}
    outer = sorted(set(grouped) | set(known), key=len)
    for folder in list(grouped):
        parent = next((o for o in outer if o != folder and _inside(folder, o)), None)
        if parent is not None:
            seen = grouped.pop(folder)
            if parent in grouped:
                grouped[parent].claude += seen.claude
                grouped[parent].codex += seen.codex

    created, suggested = [], []
    for folder in sorted(grouped):
        seen = grouped[folder]
        row = known.get(folder)
        if row is None:
            row = AgentFolder(folder=folder, status="suggested", updated_at=now)
        row.claude_sessions, row.codex_sessions = seen.claude, seen.codex
        row.first_seen, row.last_seen = seen.first, seen.last
        covering = next((p for p, root in roots if _inside(folder, root)), None)
        if row.folder in known and row.status != "suggested":
            session.add(row)
            continue
        if covering is not None:
            # Already a project's folder, or a person has since set it: nothing to decide.
            row.status, row.project_id, row.updated_at = "linked", covering.id, now
        else:
            name = Path(folder).name
            match = next(
                (
                    p
                    for p in projects
                    if not p.root_path and p.status != "archived" and _similar(name, p.name)
                ),
                None,
            )
            if match is not None:
                if row.folder not in known:
                    suggested.append(folder)
                row.status, row.project_id, row.updated_at = "suggested", match.id, now
            else:
                project = _create_project(session, folder)
                if project is None:
                    continue
                row.status, row.project_id, row.updated_at = "created", project.id, now
                roots.append((project, folder))
                created.append(project.name)
        session.add(row)
    try:
        session.commit()
    except IntegrityError:
        # Another process synced the same folder at the same moment; its result stands.
        session.rollback()
    return {"created": created, "suggested": suggested}


def _create_project(session: Session, folder: str) -> Project | None:
    base = Path(folder).name.strip() or folder
    service = ProjectService(session)
    taken = {p.name_key for p in session.scalars(select(Project))}
    name, n = base[:110], 2
    while name_key(name) in taken:
        name, n = f"{base[:110]} {n}", n + 1
    with acting_as("system", SYNC_ACTOR):
        try:
            return service.create(
                ProjectCreate(
                    name=name,
                    root_path=folder,
                    description="Added automatically from Claude Code and Codex sessions.",
                )
            )
        except Exception:  # noqa: BLE001 - a clash with a concurrent sync is not an error
            session.rollback()
            return None


def decide(
    session: Session, folder: str, action: str, project_id: str | None = None
) -> AgentFolder:
    """A person's answer about one folder: link it to a project, create one, or ignore it."""
    row = session.get(AgentFolder, folder)
    if row is None:
        raise HTTPException(
            status_code=404, detail="That folder has not been seen by Sync from agents."
        )
    now = datetime.now(UTC)
    if action == "link":
        target = ProjectService(session).get(project_id or row.project_id or "")
        if target.kind != "project":
            raise HTTPException(status_code=409, detail="Choose a project for this folder.")
        if target.root_path and normalize_folder(target.root_path) != folder:
            raise HTTPException(
                status_code=409, detail=f"{target.name} already has a folder: {target.root_path}"
            )
        ProjectService(session).update(target.id, ProjectUpdate(root_path=folder))
        row.status, row.project_id = "linked", target.id
    elif action == "create":
        project = _create_project(session, folder)
        if project is None:
            raise HTTPException(status_code=409, detail="A project could not be created for it.")
        row = session.get(AgentFolder, folder) or row
        row.status, row.project_id = "created", project.id
    elif action == "ignore":
        row.status = "ignored"
    else:
        raise HTTPException(status_code=422, detail="action must be link, create, or ignore")
    row.updated_at = now
    session.add(row)
    session.commit()
    return row


def list_folders(session: Session) -> list[dict]:
    names = {p.id: p.name for p in session.scalars(select(Project))}
    rows = session.scalars(select(AgentFolder).order_by(AgentFolder.folder))
    return [
        {
            "folder": row.folder,
            "status": row.status,
            "project_id": row.project_id,
            "project_name": names.get(row.project_id) if row.project_id else None,
            "claude_sessions": row.claude_sessions,
            "codex_sessions": row.codex_sessions,
            "last_seen": row.last_seen.isoformat() if row.last_seen else None,
        }
        for row in rows
    ]


def sync_quietly(session: Session) -> None:
    """Sync as a side task (a brief, a background loop); never let it break the caller."""
    try:
        sync_agent_folders(session)
    except Exception:  # noqa: BLE001 - syncing is best effort here
        session.rollback()


def background_sync(session_factory, stop: threading.Event, interval: float = 60.0) -> None:
    """Every minute while the app runs: sync agent folders, then delete tasks Done too long
    (only when that setting is on)."""
    from app.services.task_cleanup import cleanup_quietly

    while not stop.is_set():
        with session_factory() as session:
            sync_quietly(session)
            cleanup_quietly(session)
        stop.wait(interval)

"""Which folders belong to which project, for matching an agent's working folder to a project.

A project's folder is the one a person set (``root_path``), plus every folder Sync from agents
linked to it or created it from. Both count, so a project whose folder was chosen through the
Flatpak file picker (a document portal path such as /run/user/1000/doc/<id>/Game, which only
the app can open) still matches the real folder agents work in.

When no folder matches, the folder's Git remote can: a second clone, or a worktree kept
somewhere else, belongs to the project whose folder has the same ``origin``. Git is not run:
only the repository's own config file is read, so this stays fast and works offline.
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent_folder import AgentFolder
from app.models.project import Project
from app.services.usage import PORTAL_PREFIX, inside_folder, normalize_folder

# Folders Sync from agents decided belong to a project.
OWNING_STATUSES = ("linked", "created")
PORTAL_FOLDER = re.compile(r"^/run/user/\d+/doc/[^/]+(/|$)")
# Folders that exist only for one session: a remote session's mounted copy of a folder, and
# runtime folders that are gone after a restart. A document portal path is not one of them:
# it is how a Flatpak install keeps access to a folder the person chose.
SANDBOX_FOLDERS = (re.compile(r"^/sessions/[^/]+/mnt(/|$)"), re.compile(r"^/(proc|dev)(/|$)"))
GIT_DEPTH = 64  # parents walked up looking for a repository, a guard against odd file systems
REMOTE_SECTION = re.compile(r'^\s*\[\s*remote\s+"(?P<name>[^"]+)"\s*\]\s*$')
SECTION = re.compile(r"^\s*\[")
URL_LINE = re.compile(r"^\s*url\s*=\s*(?P<url>.+?)\s*$", re.IGNORECASE)
SCP_STYLE = re.compile(r"^(?:[^@/]+@)?(?P<host>[^:/]+):(?P<path>(?!//).+)$")


def is_portal_folder(path: str) -> bool:
    """A Flatpak document portal path the host's own folder could not be read from."""
    return PORTAL_FOLDER.match(normalize_folder(path)) is not None


def sandbox_folder(path: str) -> bool:
    """A folder that disappears with the session or the system that made it."""
    folder = normalize_folder(path)
    return any(pattern.match(folder) for pattern in SANDBOX_FOLDERS)


def project_folders(
    session: Session, *, include_archived: bool = False
) -> list[tuple[str, Project]]:
    """Every (folder, project) pair, folders normalized: each project's own folder, then the
    folders Sync from agents linked to it or made it from. Ignored and waiting folders are not
    a project's folders."""
    statement = select(Project).where(Project.kind == "project")
    if not include_archived:
        statement = statement.where(Project.status != "archived")
    projects = {p.id: p for p in session.scalars(statement)}
    pairs = [(normalize_folder(p.root_path), p) for p in projects.values() if p.root_path]
    rows = session.scalars(
        select(AgentFolder).where(
            AgentFolder.status.in_(OWNING_STATUSES), AgentFolder.project_id.is_not(None)
        )
    )
    pairs += [
        (normalize_folder(row.folder), projects[row.project_id])
        for row in rows
        if row.project_id in projects
    ]
    return pairs


def deepest_owners(folder: str, pairs: list[tuple[str, Project]]) -> list[Project]:
    """The projects owning the deepest folder that holds ``folder``: one, several when two
    projects share that folder, or none."""
    depth: dict[str, tuple[int, Project]] = {}
    for root, project in pairs:
        if inside_folder(folder, root):
            parts = len(Path(root).parts)
            if parts > depth.get(project.id, (-1, project))[0]:
                depth[project.id] = (parts, project)
    if not depth:
        return []
    best = max(parts for parts, _ in depth.values())
    return sorted((p for parts, p in depth.values() if parts == best), key=lambda p: p.name)


def _git_config(folder: str) -> Path | None:
    """The config file of the repository holding ``folder``, worktrees included."""
    if folder.startswith(PORTAL_PREFIX):
        return None
    try:
        here = Path(folder)
        if not here.is_absolute():
            return None
        for current in [here, *here.parents][:GIT_DEPTH]:
            dot_git = current / ".git"
            if dot_git.is_dir():
                return dot_git / "config"
            if dot_git.is_file():
                # A worktree or submodule: ".git" names the real git folder; a worktree's
                # "commondir" points back at the repository that holds the config.
                line = dot_git.read_text(encoding="utf-8", errors="replace").strip()
                if not line.startswith("gitdir:"):
                    return None
                git_dir = (current / line.removeprefix("gitdir:").strip()).resolve()
                common = git_dir / "commondir"
                if common.is_file():
                    target = common.read_text(encoding="utf-8", errors="replace").strip()
                    git_dir = (git_dir / target).resolve()
                return git_dir / "config"
    except (OSError, ValueError):
        return None
    return None


def normalize_remote(url: str) -> str | None:
    """One spelling per repository: https://github.com/Me/Game.git, git@github.com:me/game and
    ssh://git@github.com/me/game are the same. Hosts and paths ignore case, as on GitHub."""
    url = url.strip().strip('"')
    if not url:
        return None
    if "://" in url:
        rest = url.split("://", 1)[1]
        host, _, path = rest.partition("/")
        host = host.rsplit("@", 1)[-1].split(":", 1)[0]
    elif match := SCP_STYLE.match(url):
        host, path = match.group("host"), match.group("path")
    else:
        # A remote on this disk (a bare repository or another clone).
        return normalize_folder(url).casefold().removesuffix(".git") or None
    path = path.strip("/").removesuffix(".git").strip("/")
    if not host or not path:
        return None
    return f"{host}/{path}".casefold()


def repository_remote(folder: str) -> str | None:
    """The ``origin`` remote of the repository holding ``folder`` (else its only remote),
    normalized, or None outside a repository or when it cannot be read."""
    config = _git_config(folder)
    if config is None:
        return None
    try:
        lines = config.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    remotes: dict[str, str] = {}
    section = None
    for line in lines:
        if match := REMOTE_SECTION.match(line):
            section = match.group("name")
        elif SECTION.match(line):
            section = None
        elif section and (match := URL_LINE.match(line)):
            remotes.setdefault(section, match.group("url"))
    url = remotes.get("origin") or (next(iter(remotes.values())) if len(remotes) == 1 else None)
    return normalize_remote(url) if url else None


def remote_owners(folder: str, pairs: list[tuple[str, Project]]) -> list[Project]:
    """Projects with a folder in the same Git repository (by remote) as ``folder``."""
    remote = repository_remote(folder)
    if remote is None:
        return []
    seen: dict[str, str | None] = {}
    owners: dict[str, Project] = {}
    for root, project in pairs:
        if root not in seen:
            seen[root] = repository_remote(root)
        if seen[root] == remote:
            owners[project.id] = project
    return sorted(owners.values(), key=lambda p: p.name)

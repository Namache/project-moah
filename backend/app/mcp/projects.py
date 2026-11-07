"""Pick the right Project Moah project for an agent, or refuse to guess."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import GLOBAL_PROJECT_ID, Project
from app.services.folders import deepest_owners, project_folders, remote_owners, sandbox_folder
from app.services.projects import name_key
from app.services.usage import inside_folder as _inside
from app.services.usage import normalize_folder


class ProjectChoiceError(ValueError):
    """Raised with a message an agent can act on, and, when known, why nothing matched."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


def _folder(path: str) -> str:
    """Compare folders as written, so a folder the app cannot open (an agent's working folder in
    another sandbox) still matches. /var/home and /home, and portal paths, are one spelling."""
    try:
        path = str(Path(path).expanduser().resolve(strict=False))
    except OSError:
        pass
    return normalize_folder(path)


def resolve_project(
    session: Session, project: str | None, cwd: str | None, default: str | None = None
) -> tuple[Project, str]:
    """Return (project, how it was found). Explicit choices win; a folder is matched only
    when exactly one project owns the best-matching folder: its own folder or one Sync from
    agents linked to it, else a folder in the same Git repository (by remote)."""
    explicit = (project or "").strip() or (default or "").strip()
    if explicit.lower() in (GLOBAL_PROJECT_ID, "__global__"):
        found = session.get(Project, GLOBAL_PROJECT_ID)
        if found is not None:
            return found, "project argument" if project else "server setting"
    if explicit:
        # Prefer an exact id, then slug, then name, so one value never matches two projects.
        found = (
            session.get(Project, explicit)
            or session.scalar(select(Project).where(Project.slug == explicit.lower()))
            or session.scalar(select(Project).where(Project.name_key == name_key(explicit)))
        )
        if found is None:
            names = ", ".join(
                sorted(
                    p.slug
                    for p in session.scalars(select(Project).where(Project.kind == "project"))
                )
            )
            raise ProjectChoiceError(
                f"No Project Moah project matches '{explicit}'. Known projects: {names or 'none'}."
            )
        return found, "project argument" if project else "server setting"

    folder = _folder(cwd or os.getcwd())
    pairs = project_folders(session)
    found, how = deepest_owners(folder, pairs), "working directory"
    if not found:
        # No folder of any project holds it: a clone or worktree elsewhere still belongs to the
        # project whose folder shares its Git remote.
        found, how = remote_owners(folder, pairs), "git remote"
    if len(found) == 1:
        return found[0], how
    if found:
        names = "\n".join(f"- {p.name} ({p.slug})" for p in found)
        raise ProjectChoiceError(
            "Unable to safely determine Project Moah project.\n\nCandidates:\n"
            f"{names}\n\nSpecify project explicitly."
        )
    raise ProjectChoiceError(
        "Unable to safely determine Project Moah project from the working directory "
        f"({folder}). Specify project explicitly, or call brain_list_projects.",
        hint=why_no_match(session, folder),
    )


def why_no_match(session: Session, folder: str) -> str | None:
    """Why a folder matched no project, when Project Moah knows, said so a person can fix it."""
    from app.models.agent_folder import AgentFolder
    from app.services.agent_sync import project_folder

    if project_folder(folder) is None or sandbox_folder(folder):
        return (
            "This is a temporary, system or home folder, which never becomes a project. "
            "Start the session in the project's own folder."
        )
    rows = [
        row
        for row in session.scalars(select(AgentFolder))
        if _inside(folder, normalize_folder(row.folder))
    ]
    row = max(rows, key=lambda r: len(r.folder), default=None)
    if row is not None and row.status == "suggested" and row.project_id:
        target = session.get(Project, row.project_id)
        if target is not None:
            return (
                f"Sync from agents is waiting for the person to confirm that this folder belongs "
                f"to {target.name}: they answer it on the Projects page."
            )
    if row is not None and row.status == "ignored":
        return "The person chose to ignore this folder in Sync from agents (Projects page)."
    if row is not None and row.project_id:
        target = session.get(Project, row.project_id)
        if target is not None and target.status == "archived":
            return f"This folder belongs to {target.name}, which is archived."
    return None

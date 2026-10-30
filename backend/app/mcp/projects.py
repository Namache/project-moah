"""Pick the right Project Moah project for an agent, or refuse to guess."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import GLOBAL_PROJECT_ID, Project
from app.services.projects import name_key
from app.services.usage import normalize_folder


class ProjectChoiceError(ValueError):
    """Raised with a message an agent can act on."""


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


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
    when exactly one project owns the best-matching repository folder."""
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
    matches: list[tuple[int, Project]] = []
    for candidate in session.scalars(
        select(Project).where(Project.status != "archived", Project.kind == "project")
    ):
        if not candidate.root_path:
            continue
        root = _folder(candidate.root_path)
        if _inside(folder, root):
            matches.append((len(Path(root).parts), candidate))
    if matches:
        best = max(depth for depth, _ in matches)
        winners = sorted((p for depth, p in matches if depth == best), key=lambda p: p.name)
        if len(winners) == 1:
            return winners[0], "working directory"
        names = "\n".join(f"- {p.name} ({p.slug})" for p in winners)
        raise ProjectChoiceError(
            "Unable to safely determine Project Moah project.\n\nCandidates:\n"
            f"{names}\n\nSpecify project explicitly."
        )
    raise ProjectChoiceError(
        "Unable to safely determine Project Moah project from the working directory "
        f"({folder}). Specify project explicitly, or call brain_list_projects."
    )

import re
import unicodedata
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.project import Project
from app.repositories.projects import ProjectRepository
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.services.activity import ActivityService
from app.services.text import name_key


def slugify(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).casefold()
    without_marks = "".join(c for c in normalized if not unicodedata.combining(c))
    slug = re.sub(r"[^\w]+", "-", without_marks.replace("_", "-"), flags=re.UNICODE)
    return slug.strip("-") or "project"


class ProjectService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.projects = ProjectRepository(session)

    def list(self, *, include_archived: bool = False) -> list[Project]:
        return self.projects.list(include_archived=include_archived)

    def get(self, project_id: str) -> Project:
        project = self.projects.get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    def create(self, payload: ProjectCreate) -> Project:
        key = name_key(payload.name)
        self._ensure_unique_name(key)
        slug_base = slugify(payload.name)
        slug = slug_base
        suffix = 2
        while self.projects.slug_exists(slug):
            slug = f"{slug_base}-{suffix}"
            suffix += 1

        now = datetime.now(UTC)
        project = Project(
            id=str(uuid4()),
            name=payload.name,
            name_key=key,
            slug=slug,
            description=payload.description,
            icon=payload.icon,
            accent=payload.accent,
            root_path=payload.root_path,
            task_prefix=payload.task_prefix,
            status=payload.status,
            created_at=now,
            updated_at=now,
            archived_at=now if payload.status == "archived" else None,
        )
        self.session.add(project)
        self.session.flush()
        ActivityService(self.session).record(
            project.id,
            "PROJECT_CREATED",
            entity_type="project",
            entity_id=project.id,
            metadata={"name": project.name},
        )
        self._commit()
        return project

    def update(self, project_id: str, payload: ProjectUpdate) -> Project:
        project = self.get(project_id)
        changes = payload.model_dump(exclude_unset=True)
        if project.kind == "global" and set(changes) - {"description"}:
            raise HTTPException(
                status_code=409, detail="The Global scope can only have its description changed."
            )
        previous_status = project.status
        if "name" in changes and changes["name"] != project.name:
            key = name_key(changes["name"])
            self._ensure_unique_name(key, project_id=project.id)
            project.name_key = key

        for field, value in changes.items():
            setattr(project, field, value)

        if "status" in changes:
            project.archived_at = datetime.now(UTC) if project.status == "archived" else None
        project.updated_at = datetime.now(UTC)
        event_type = (
            "PROJECT_ARCHIVED"
            if project.status == "archived" and previous_status != "archived"
            else "PROJECT_RESTORED"
            if previous_status == "archived" and project.status != "archived"
            else "PROJECT_UPDATED"
        )
        ActivityService(self.session).record(
            project.id,
            event_type,
            entity_type="project",
            entity_id=project.id,
            metadata={"name": project.name, "changed_fields": sorted(changes)},
        )
        self._commit()
        return project

    def archive(self, project_id: str) -> Project:
        project = self.get(project_id)
        if project.kind == "global":
            raise HTTPException(status_code=409, detail="The Global scope cannot be archived.")
        if project.status != "archived":
            project.status = "archived"
            project.archived_at = datetime.now(UTC)
            project.updated_at = project.archived_at
            ActivityService(self.session).record(
                project.id,
                "PROJECT_ARCHIVED",
                entity_type="project",
                entity_id=project.id,
                metadata={"name": project.name},
            )
            self._commit()
        return project

    def _ensure_unique_name(self, key: str, project_id: str | None = None) -> None:
        existing = self.projects.get_by_name_key(key)
        if existing is not None and existing.id != project_id:
            raise HTTPException(status_code=409, detail="A project with this name already exists")

    def _commit(self) -> None:
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise HTTPException(
                status_code=409, detail="Project name or slug already exists"
            ) from exc

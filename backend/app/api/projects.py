from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services.projects import ProjectService

router = APIRouter(prefix="/api/projects", tags=["projects"])
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.get("", response_model=list[ProjectRead])
def list_projects(session: DatabaseSession, include_archived: bool = False) -> list[ProjectRead]:
    projects = ProjectService(session).list(include_archived=include_archived)
    return [ProjectRead.model_validate(project) for project in projects]


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, session: DatabaseSession) -> ProjectRead:
    return ProjectRead.model_validate(ProjectService(session).create(payload))


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: str, session: DatabaseSession) -> ProjectRead:
    return ProjectRead.model_validate(ProjectService(session).get(project_id))


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: str, payload: ProjectUpdate, session: DatabaseSession
) -> ProjectRead:
    return ProjectRead.model_validate(ProjectService(session).update(project_id, payload))


@router.post("/{project_id}/archive", response_model=ProjectRead)
def archive_project(project_id: str, session: DatabaseSession) -> ProjectRead:
    return ProjectRead.model_validate(ProjectService(session).archive(project_id))

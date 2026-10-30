"""Phase 7 routes: file notes, the repository tree, and read-only Git details."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.schemas.files import (
    CommitLink,
    CommitList,
    CommitRead,
    FileCreate,
    FileRead,
    FileTree,
    FileUpdate,
    GitStatus,
)
from app.services.files import FileService
from app.services.projects import ProjectService

router = APIRouter(prefix="/api/projects/{project_id}", tags=["files"])
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.get("/files", response_model=list[FileRead])
def list_files(
    project_id: str,
    session: DatabaseSession,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> list[FileRead]:
    return FileService(session).list(project_id, q=q)


@router.post("/files", response_model=FileRead, status_code=status.HTTP_201_CREATED)
def create_file(project_id: str, payload: FileCreate, session: DatabaseSession) -> FileRead:
    return FileService(session).create(project_id, payload)


@router.get("/files/tree", response_model=FileTree)
def file_tree(project_id: str, session: DatabaseSession) -> FileTree:
    return FileService(session).tree(project_id)


@router.get("/files/by-path", response_model=FileRead)
def get_file_by_path(
    project_id: str, session: DatabaseSession, path: Annotated[str, Query(max_length=1024)]
) -> FileRead:
    return FileService(session).read(project_id, path)


@router.get("/files/{file_id}", response_model=FileRead)
def get_file(project_id: str, file_id: str, session: DatabaseSession) -> FileRead:
    return FileService(session).read(project_id, file_id)


@router.patch("/files/{file_id}", response_model=FileRead)
def update_file(
    project_id: str, file_id: str, payload: FileUpdate, session: DatabaseSession
) -> FileRead:
    return FileService(session).update(project_id, file_id, payload)


@router.post("/files/{file_id}/reviewed", response_model=FileRead)
def mark_file_reviewed(project_id: str, file_id: str, session: DatabaseSession) -> FileRead:
    return FileService(session).mark_reviewed(project_id, file_id)


@router.get("/files/{file_id}/git", response_model=CommitList)
def file_git_history(project_id: str, file_id: str, session: DatabaseSession) -> CommitList:
    return FileService(session).file_history(project_id, file_id)


@router.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file_notes(project_id: str, file_id: str, session: DatabaseSession) -> Response:
    """Removes Project Moah's notes only. The file in the repository is never touched."""
    FileService(session).delete(project_id, file_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/git", response_model=GitStatus)
def git_status(project_id: str, session: DatabaseSession) -> GitStatus:
    return FileService(session).git.status(ProjectService(session).get(project_id))


@router.get("/git/commits", response_model=CommitList)
def git_commits(
    project_id: str,
    session: DatabaseSession,
    task: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> CommitList:
    return FileService(session).commits(project_id, limit=limit, task=task)


@router.post(
    "/git/commits/{sha}/tasks", response_model=CommitRead, status_code=status.HTTP_201_CREATED
)
def link_commit(
    project_id: str, sha: str, payload: CommitLink, session: DatabaseSession
) -> CommitRead:
    return FileService(session).link_commit(project_id, sha, payload.task)


@router.delete("/git/commits/{sha}/tasks/{task}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_commit(project_id: str, sha: str, task: str, session: DatabaseSession) -> Response:
    FileService(session).unlink_commit(project_id, sha, task)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

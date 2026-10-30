"""Phase 2 routes. Handlers only translate HTTP to service calls."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.schemas.project import ProjectRead
from app.schemas.task import (
    CriterionCreate,
    CriterionUpdate,
    MilestoneCreate,
    MilestoneRead,
    MilestoneUpdate,
    ProjectOverview,
    RelationshipCreate,
    TaskCreate,
    TaskDetail,
    TaskMove,
    TaskStatus,
    TaskSummary,
    TaskUpdate,
    WorkspaceTask,
)
from app.services.agent_prompts import work_prompt
from app.services.discovery import discover_quietly
from app.services.milestones import MilestoneService
from app.services.projects import ProjectService
from app.services.settings import get_agent_settings
from app.services.tasks import TaskService

router = APIRouter(prefix="/api", tags=["tasks"])
DatabaseSession = Annotated[Session, Depends(get_session)]
P = "/projects/{project_id}"
T = P + "/tasks/{task_ref}"


class FocusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str | None = Field(default=None, max_length=64)


# ---- milestones -------------------------------------------------------------------------


@router.get(P + "/milestones", response_model=list[MilestoneRead])
def list_milestones(
    project_id: str, session: DatabaseSession, include_archived: bool = False
) -> list[MilestoneRead]:
    return MilestoneService(session).list(project_id, include_archived=include_archived)


@router.post(P + "/milestones", response_model=MilestoneRead, status_code=status.HTTP_201_CREATED)
def create_milestone(
    project_id: str, payload: MilestoneCreate, session: DatabaseSession
) -> MilestoneRead:
    return MilestoneService(session).create(project_id, payload)


@router.patch(P + "/milestones/{milestone_id}", response_model=MilestoneRead)
def update_milestone(
    project_id: str, milestone_id: str, payload: MilestoneUpdate, session: DatabaseSession
) -> MilestoneRead:
    return MilestoneService(session).update(project_id, milestone_id, payload)


# ---- tasks ------------------------------------------------------------------------------


@router.get(P + "/tasks", response_model=list[TaskSummary])
def list_tasks(
    project_id: str,
    session: DatabaseSession,
    status_filter: Annotated[list[TaskStatus] | None, Query(alias="status")] = None,
    milestone_id: str | None = None,
    include_archived: bool = False,
) -> list[TaskSummary]:
    return TaskService(session).list(
        project_id,
        statuses=status_filter,
        milestone_id=milestone_id,
        include_archived=include_archived,
    )


@router.post(P + "/tasks", response_model=TaskDetail, status_code=status.HTTP_201_CREATED)
def create_task(project_id: str, payload: TaskCreate, session: DatabaseSession) -> TaskDetail:
    created = TaskService(session).create(project_id, payload)
    discover_quietly(session, project_id, f"task:{created.id}")
    return created


@router.get(T, response_model=TaskDetail)
def get_task(project_id: str, task_ref: str, session: DatabaseSession) -> TaskDetail:
    return TaskService(session).detail(project_id, task_ref)


@router.patch(T, response_model=TaskDetail)
def update_task(
    project_id: str, task_ref: str, payload: TaskUpdate, session: DatabaseSession
) -> TaskDetail:
    updated = TaskService(session).update(project_id, task_ref, payload)
    if {"title", "description", "next_action"} & payload.model_fields_set:
        discover_quietly(session, project_id, f"task:{updated.id}")
    return updated


@router.delete(T, status_code=status.HTTP_204_NO_CONTENT)
def delete_task(project_id: str, task_ref: str, session: DatabaseSession) -> Response:
    TaskService(session).delete(project_id, task_ref)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(T + "/move", response_model=TaskDetail)
def move_task(
    project_id: str, task_ref: str, payload: TaskMove, session: DatabaseSession
) -> TaskDetail:
    return TaskService(session).move(project_id, task_ref, payload)


@router.post(T + "/start", response_model=TaskDetail)
def start_task(project_id: str, task_ref: str, session: DatabaseSession) -> TaskDetail:
    return TaskService(session).start_work(project_id, task_ref)


@router.post(T + "/criteria", response_model=TaskDetail, status_code=status.HTTP_201_CREATED)
def add_criterion(
    project_id: str, task_ref: str, payload: CriterionCreate, session: DatabaseSession
) -> TaskDetail:
    return TaskService(session).add_criterion(project_id, task_ref, payload)


@router.patch(T + "/criteria/{criterion_id}", response_model=TaskDetail)
def update_criterion(
    project_id: str,
    task_ref: str,
    criterion_id: str,
    payload: CriterionUpdate,
    session: DatabaseSession,
) -> TaskDetail:
    return TaskService(session).update_criterion(project_id, task_ref, criterion_id, payload)


@router.delete(T + "/criteria/{criterion_id}", response_model=TaskDetail)
def delete_criterion(
    project_id: str, task_ref: str, criterion_id: str, session: DatabaseSession
) -> TaskDetail:
    return TaskService(session).delete_criterion(project_id, task_ref, criterion_id)


@router.post(T + "/relationships", response_model=TaskDetail, status_code=status.HTTP_201_CREATED)
def add_relationship(
    project_id: str, task_ref: str, payload: RelationshipCreate, session: DatabaseSession
) -> TaskDetail:
    return TaskService(session).add_relationship(project_id, task_ref, payload)


@router.delete(T + "/relationships/{relationship_id}", response_model=TaskDetail)
def remove_relationship(
    project_id: str, task_ref: str, relationship_id: str, session: DatabaseSession
) -> TaskDetail:
    return TaskService(session).remove_relationship(project_id, task_ref, relationship_id)


# ---- focus and overviews ----------------------------------------------------------------


@router.put(P + "/focus", response_model=ProjectRead)
def set_focus(project_id: str, payload: FocusUpdate, session: DatabaseSession) -> ProjectRead:
    return ProjectRead.model_validate(TaskService(session).set_focus(project_id, payload.task))


@router.get(P + "/overview", response_model=ProjectOverview)
def project_overview(project_id: str, session: DatabaseSession) -> ProjectOverview:
    ProjectService(session).get(project_id)
    return TaskService(session).overviews([project_id])[0]


@router.get("/workspace/overviews", response_model=list[ProjectOverview])
def workspace_overviews(session: DatabaseSession) -> list[ProjectOverview]:
    projects = ProjectService(session).list()
    return TaskService(session).overviews([p.id for p in projects])


@router.get("/tasks", response_model=list[WorkspaceTask])
def workspace_tasks(
    session: DatabaseSession,
    status_filter: Annotated[list[TaskStatus] | None, Query(alias="status")] = None,
    project_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[WorkspaceTask]:
    return TaskService(session).list_workspace(
        statuses=status_filter, project_id=project_id, limit=limit, offset=offset
    )


@router.get("/projects/{project_id}/tasks/{ref}/work-prompt")
def task_work_prompt(
    project_id: str,
    ref: str,
    session: DatabaseSession,
    agent: Annotated[Literal["claude", "codex"] | None, Query()] = None,
) -> dict:
    """A prompt for completing the task, and the desktop-app link that opens it unsent."""
    project = ProjectService(session).get(project_id)
    chosen = agent or get_agent_settings(session).default_agent
    return work_prompt(session, project, ref, chosen)

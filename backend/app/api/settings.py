"""App-wide settings: agents (default agent, second opinions, how to start each one) and tasks."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.services.settings import (
    AgentSettings,
    AgentSettingsUpdate,
    TaskSettings,
    TaskSettingsUpdate,
    get_agent_settings,
    get_task_settings,
    update_agent_settings,
    update_task_settings,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.get("/agents", response_model=AgentSettings)
def read_agent_settings(session: DatabaseSession) -> AgentSettings:
    return get_agent_settings(session)


@router.patch("/agents", response_model=AgentSettings)
def change_agent_settings(payload: AgentSettingsUpdate, session: DatabaseSession) -> AgentSettings:
    return update_agent_settings(session, payload)


@router.get("/tasks", response_model=TaskSettings)
def read_task_settings(session: DatabaseSession) -> TaskSettings:
    return get_task_settings(session)


@router.patch("/tasks", response_model=TaskSettings)
def change_task_settings(payload: TaskSettingsUpdate, session: DatabaseSession) -> TaskSettings:
    return update_task_settings(session, payload)

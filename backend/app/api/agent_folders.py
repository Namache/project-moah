"""Sync from agents: folders Claude Code and Codex worked in, and a person's answers about them."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.services.agent_sync import decide, list_folders, sync_agent_folders

router = APIRouter(prefix="/api/agent-folders", tags=["agent sync"])
DatabaseSession = Annotated[Session, Depends(get_session)]


class FolderDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    folder: str = Field(min_length=1, max_length=4096)
    action: Literal["link", "create", "ignore"]
    project_id: str | None = Field(default=None, max_length=36)


# Plain functions so reading the agents' logs runs in the thread pool.
@router.get("")
def get_folders(session: DatabaseSession) -> dict[str, Any]:
    result = sync_agent_folders(session)
    return {**result, "folders": list_folders(session)}


@router.post("/decide")
def decide_folder(payload: FolderDecision, session: DatabaseSession) -> dict[str, Any]:
    decide(session, payload.folder, payload.action, payload.project_id)
    return {"folders": list_folders(session)}

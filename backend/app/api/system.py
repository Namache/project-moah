from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core import error_log
from app.db.session import get_session
from app.services.agent_connect import connect_agents
from app.services.builds import UpdateWatch, update_status
from app.services.system import agent_launch, diagnostics, export_backup

router = APIRouter(prefix="/api/system", tags=["system"])
DatabaseSession = Annotated[Session, Depends(get_session)]
# This service's own build, noted when it started, to tell the window about a newer install.
_watch: UpdateWatch | None = None


def watch() -> UpdateWatch:
    global _watch
    if _watch is None:
        _watch = UpdateWatch()
    return _watch


@router.get("/agent-command")
def get_agent_command() -> dict[str, Any]:
    """The command agents use to start this installation's MCP server."""
    return agent_launch()


@router.post("/connect-agents")
def post_connect_agents() -> dict[str, Any]:
    """Connect Claude Code and Codex, for the Connect button in Help."""
    return {"results": connect_agents()}


@router.get("/update")
def get_update(session: DatabaseSession) -> dict[str, Any]:
    """Whether Project Moah was updated while this window was open, so it can offer a restart."""
    return update_status(session, watch())


@router.get("/diagnostics")
def get_diagnostics(session: DatabaseSession) -> dict[str, Any]:
    return diagnostics(session)


class WindowError(BaseModel):
    message: str = Field(min_length=1, max_length=4_000)
    detail: str = Field(default="", max_length=20_000)


@router.get("/errors")
def get_errors() -> dict[str, Any]:
    """The local error log, newest first. It is read from files on this computer only."""
    return error_log.read()


@router.post("/errors", status_code=204)
def post_error(error: WindowError) -> None:
    """An error in the app window itself, which cannot write files."""
    error_log.write("window", error.message, error.detail)


@router.delete("/errors", status_code=204)
def delete_errors() -> None:
    error_log.clear()


@router.get("/export")
def export() -> FileResponse:
    """Download a backup of all Project Moah data. Source repositories are not included."""
    try:
        path, name = export_backup()
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    def cleanup() -> None:
        path.unlink(missing_ok=True)
        Path(path.parent).rmdir()

    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=name,
        background=BackgroundTask(cleanup),
    )

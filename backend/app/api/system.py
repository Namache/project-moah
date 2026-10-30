from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.db.session import get_session
from app.services.system import diagnostics, export_backup

router = APIRouter(prefix="/api/system", tags=["system"])
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.get("/diagnostics")
def get_diagnostics(session: DatabaseSession) -> dict[str, Any]:
    return diagnostics(session)


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

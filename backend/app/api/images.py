"""Images on tasks and memory records. The body of an upload is the image file itself."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models.image import MAX_IMAGE_BYTES
from app.schemas.image import ImageRead
from app.services.errors import invalid
from app.services.images import ImageService

router = APIRouter(prefix="/api/projects/{project_id}", tags=["images"])
DatabaseSession = Annotated[Session, Depends(get_session)]
OwnerPath = Literal["tasks", "memory"]


def _kind(owner: OwnerPath) -> Literal["task", "memory"]:
    return "task" if owner == "tasks" else "memory"


@router.get("/{owner}/{ref}/images", response_model=list[ImageRead])
def list_images(project_id: str, owner: OwnerPath, ref: str, session: DatabaseSession):
    return ImageService(session).list(project_id, _kind(owner), ref)


@router.post("/{owner}/{ref}/images", response_model=ImageRead, status_code=status.HTTP_201_CREATED)
async def attach_image(
    project_id: str,
    owner: OwnerPath,
    ref: str,
    request: Request,
    session: DatabaseSession,
    filename: Annotated[str | None, Query(max_length=255)] = None,
) -> ImageRead:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_IMAGE_BYTES:
        raise invalid(f"Images can be at most {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_IMAGE_BYTES:
            raise invalid(f"Images can be at most {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    return ImageService(session).add(project_id, _kind(owner), ref, bytes(data), filename)


@router.get("/images/{image_id}", response_class=Response)
def image_file(project_id: str, image_id: str, session: DatabaseSession) -> Response:
    image = ImageService(session).get(project_id, image_id)
    return Response(
        image.data,
        media_type=image.media_type,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.delete("/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_image(project_id: str, image_id: str, session: DatabaseSession) -> Response:
    ImageService(session).delete(project_id, image_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

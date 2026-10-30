"""Images attached to tasks and memory records: checked, stored, listed, served.

An image is accepted only when its first bytes say it is a PNG, JPEG, WebP or GIF; the name
and the type the sender claims are never trusted. Size limits match what Claude accepts.
"""

from __future__ import annotations

import struct
from collections.abc import Iterable
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, undefer

from app.models.image import MAX_IMAGE_BYTES, MAX_IMAGES_PER_RECORD, Image
from app.schemas.image import ImageRead
from app.services.activity import ActivityService, current_actor
from app.services.errors import invalid, not_found

Owner = Literal["task", "memory"]


def sniff(data: bytes) -> tuple[str, int | None, int | None]:
    """The real media type of an image and its size in pixels, from its header."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return "image/png", width, height
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        width, height = struct.unpack("<HH", data[6:10])
        return "image/gif", width, height
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", *_webp_size(data)
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", *_jpeg_size(data)
    raise invalid("Only PNG, JPEG, WebP and GIF images can be attached")


def _webp_size(data: bytes) -> tuple[int | None, int | None]:
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        return (
            1 + int.from_bytes(data[24:27], "little"),
            1 + int.from_bytes(data[27:30], "little"),
        )
    if chunk == b"VP8 " and len(data) >= 30:
        width, height = struct.unpack("<HH", data[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if chunk == b"VP8L" and len(data) >= 25:
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None, None


def _jpeg_size(data: bytes) -> tuple[int | None, int | None]:
    at = 2
    while at + 9 < len(data):
        if data[at] != 0xFF:
            return None, None
        marker = data[at + 1]
        if marker == 0xFF:  # padding
            at += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            at += 2
            continue
        length = int.from_bytes(data[at + 2 : at + 4], "big")
        # Start-of-frame markers carry the size; C4, C8 and CC are other tables.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[at + 5 : at + 9])
            return width, height
        at += 2 + length
    return None, None


def clean_filename(name: str | None, media_type: str) -> str:
    name = " ".join((name or "").replace("/", " ").replace("\\", " ").split())[:200]
    return name or f"pasted image.{media_type.split('/')[1].replace('jpeg', 'jpg')}"


class ImageService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _owner_id(self, project_id: str, kind: Owner, ref: str) -> tuple[str, str]:
        # Imported here: both services build their reads with this one.
        if kind == "task":
            from app.services.tasks import TaskService

            task = TaskService(self.session).get(project_id, ref)
            return task.id, task.human_id
        from app.services.memory import MemoryService

        memory = MemoryService(self.session).get(project_id, ref)
        return memory.id, memory.human_id

    @staticmethod
    def _column(kind: Owner):
        return Image.task_id if kind == "task" else Image.memory_id

    def for_records(self, kind: Owner, ids: Iterable[str]) -> dict[str, list[ImageRead]]:
        """Every image of these records, oldest first, without loading the bytes."""
        ids = list(ids)
        found: dict[str, list[ImageRead]] = {i: [] for i in ids}
        if not ids:
            return found
        column = self._column(kind)
        rows = self.session.scalars(
            select(Image).where(column.in_(ids)).order_by(Image.created_at, Image.id)
        )
        for image in rows:
            found[image.task_id or image.memory_id].append(ImageRead.model_validate(image))
        return found

    def list(self, project_id: str, kind: Owner, ref: str) -> list[ImageRead]:
        owner_id, _ = self._owner_id(project_id, kind, ref)
        return self.for_records(kind, [owner_id])[owner_id]

    def add(
        self, project_id: str, kind: Owner, ref: str, data: bytes, filename: str | None
    ) -> ImageRead:
        if not data:
            raise invalid("The image is empty")
        if len(data) > MAX_IMAGE_BYTES:
            raise invalid(f"Images can be at most {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
        media_type, width, height = sniff(data)
        owner_id, human_id = self._owner_id(project_id, kind, ref)
        column = self._column(kind)
        count = self.session.scalar(select(func.count(Image.id)).where(column == owner_id))
        if count >= MAX_IMAGES_PER_RECORD:
            raise invalid(f"{human_id} already has {MAX_IMAGES_PER_RECORD} images")
        actor_type, actor_name = current_actor()
        image = Image(
            project_id=project_id,
            task_id=owner_id if kind == "task" else None,
            memory_id=owner_id if kind == "memory" else None,
            filename=clean_filename(filename, media_type),
            media_type=media_type,
            size_bytes=len(data),
            width=width,
            height=height,
            data=data,
            created_by=actor_name or actor_type,
        )
        self.session.add(image)
        self.session.flush()
        self._record(project_id, "IMAGE_ATTACHED", kind, owner_id, human_id, image)
        self.session.commit()
        return ImageRead.model_validate(image)

    def get(self, project_id: str, image_id: str) -> Image:
        image = self.session.scalar(
            select(Image)
            .options(undefer(Image.data))
            .where(Image.project_id == project_id, Image.id == image_id)
        )
        if image is None:
            raise not_found("Image not found in this project")
        return image

    def delete(self, project_id: str, image_id: str) -> None:
        image = self.get(project_id, image_id)
        kind: Owner = "task" if image.task_id else "memory"
        owner_id = image.task_id or image.memory_id
        self._record(project_id, "IMAGE_REMOVED", kind, owner_id, None, image)
        self.session.delete(image)
        self.session.commit()

    def _record(
        self,
        project_id: str,
        event: str,
        kind: Owner,
        owner_id: str,
        human_id: str | None,
        image: Image,
    ) -> None:
        ActivityService(self.session).record(
            project_id,
            event,
            entity_type=kind,
            entity_id=owner_id,
            task_id=owner_id if kind == "task" else None,
            metadata={"image": image.id, "filename": image.filename, "record": human_id},
        )

"""Images attached to a task or a memory record.

The bytes live in the database next to the record, so a backup of the database file is a
backup of the images too, and deleting the record deletes its images.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
)
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base
from app.models.project import utc_now

IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # what Claude accepts for one image
MAX_IMAGES_PER_RECORD = 10


class Image(Base):
    __tablename__ = "images"
    __table_args__ = (
        CheckConstraint("(task_id IS NULL) <> (memory_id IS NULL)", name="ck_images_one_owner"),
        CheckConstraint(
            f"media_type IN ({', '.join(repr(t) for t in IMAGE_TYPES)})",
            name="ck_images_media_type",
        ),
        CheckConstraint(f"size_bytes BETWEEN 1 AND {MAX_IMAGE_BYTES}", name="ck_images_size"),
        Index("ix_images_task", "task_id"),
        Index("ix_images_memory", "memory_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="CASCADE")
    )
    memory_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("memories.id", ondelete="CASCADE")
    )
    filename: Mapped[str] = mapped_column(String(200), nullable=False)
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    # Lists never need the bytes; only a request for the image itself loads them.
    data: Mapped[bytes] = deferred(mapped_column(LargeBinary, nullable=False))
    created_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

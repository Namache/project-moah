"""Reviews of finished work: what an agent did on a task, and what the person decided.

An agent that finishes a task writes a review (what was done, what was not, how to check it,
screenshots). The task waits in status review until the person accepts it (the task moves to
Done) or sends it back with comments (the task is worked on again). Each send-back starts a new
round. An agent that cannot go on without the person asks a question instead: the task waits in
Blocked until the person answers, and the answer goes back to the agent the same way. A checkpoint
that says it waits for the person (see services/review_waits.py) opens such a question too.
Files live in the database next to the review, like images on tasks, so a backup of the database
is a backup of the screenshots too.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base
from app.models.image import IMAGE_TYPES, MAX_IMAGE_BYTES
from app.models.project import utc_now

# pending: waiting for the person. replaced: the agent sent a newer round before a decision.
# answered: the person answered an agent's question.
REVIEW_STATUSES = ("pending", "accepted", "rejected", "answered", "replaced")
# work: an account of finished work. question: an agent stopped to ask the person something.
REVIEW_KINDS = ("work", "question")
# screenshot: the agent's evidence. feedback: what the person attached to their comment.
REVIEW_FILE_KINDS = ("screenshot", "feedback")
TEXT_FILE_TYPE = "text/plain"
REVIEW_FILE_TYPES = (*IMAGE_TYPES, TEXT_FILE_TYPE)
MAX_REVIEW_FILE_BYTES = MAX_IMAGE_BYTES
MAX_TEXT_FILE_BYTES = 1024 * 1024
MAX_FILES_PER_KIND = 10


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class TaskReview(Base):
    __tablename__ = "task_reviews"
    __table_args__ = (
        CheckConstraint(_in("status", REVIEW_STATUSES), name="ck_task_reviews_status"),
        CheckConstraint(_in("kind", REVIEW_KINDS), name="ck_task_reviews_kind"),
        CheckConstraint("round > 0", name="ck_task_reviews_round"),
        UniqueConstraint("task_id", "round", name="uq_task_reviews_task_round"),
        Index("ix_task_reviews_status_created", "status", "created_at"),
        Index("ix_task_reviews_project_status", "project_id", "status"),
        Index("ix_task_reviews_reviewed", "reviewed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    round: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Who did the work: "claude", "codex", another agent's name, or "human".
    agent: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False, default="work")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    done: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    not_done: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    how_to_check: Mapped[str | None] = mapped_column(Text)
    # Free Markdown for everything else: tables, code, notes.
    details: Mapped[str | None] = mapped_column(Text)
    # A question's answers the person can pick from (the question itself is the summary).
    options: Mapped[list[str] | None] = mapped_column(JSON)
    # True when Moah wrote it from the task's checkpoint because the agent wrote none.
    generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The person's comment with their decision.
    comment: Mapped[str | None] = mapped_column(Text)
    # Set when the person decided by moving the task on the board instead of in Review: the
    # column it went to (completed accepts the work, in_progress sends it back).
    moved_to: Mapped[str | None] = mapped_column(String(20))
    # Tasks the person made from this round's leftovers: [{"text": ..., "task_id": ...}].
    follow_ups: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    # For a question Moah opened from an agent's checkpoint that waits for the person: the
    # newest such checkpoint. Its later notes update the round; one that moves on settles it.
    checkpoint_id: Mapped[str | None] = mapped_column(String(36))


class ReviewFile(Base):
    __tablename__ = "review_files"
    __table_args__ = (
        CheckConstraint(_in("kind", REVIEW_FILE_KINDS), name="ck_review_files_kind"),
        CheckConstraint(_in("media_type", REVIEW_FILE_TYPES), name="ck_review_files_media_type"),
        CheckConstraint(
            f"size_bytes BETWEEN 1 AND {MAX_REVIEW_FILE_BYTES}", name="ck_review_files_size"
        ),
        Index("ix_review_files_review", "review_id", "kind", "sort_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    review_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("task_reviews.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    filename: Mapped[str] = mapped_column(String(200), nullable=False)
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    caption: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data: Mapped[bytes] = deferred(mapped_column(LargeBinary, nullable=False))
    created_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

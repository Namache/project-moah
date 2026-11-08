"""Review routes: the timeline of finished work, one task's review, and the person's decision."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models.review import MAX_REVIEW_FILE_BYTES
from app.schemas.review import (
    FollowUpCreate,
    PendingReviews,
    ReviewDecision,
    ReviewDetail,
    ReviewFileRead,
    ReviewReopen,
    ReviewTimeline,
)
from app.services.agent_prompts import fix_prompt
from app.services.errors import invalid
from app.services.projects import ProjectService
from app.services.reviews import ReviewService
from app.services.settings import get_agent_settings

router = APIRouter(prefix="/api", tags=["reviews"])
DatabaseSession = Annotated[Session, Depends(get_session)]
TASK = "/projects/{project_id}/tasks/{ref}/review"
TOO_BIG = f"Files can be at most {MAX_REVIEW_FILE_BYTES // (1024 * 1024)} MB"


@router.get("/reviews", response_model=ReviewTimeline)
def review_timeline(
    session: DatabaseSession,
    project_id: Annotated[str | None, Query(max_length=36)] = None,
    reviewed_limit: Annotated[int, Query(ge=1, le=300)] = 80,
) -> ReviewTimeline:
    return ReviewService(session).timeline(project_id, reviewed_limit)


@router.get("/reviews/pending", response_model=PendingReviews)
def pending_reviews(session: DatabaseSession) -> PendingReviews:
    return ReviewService(session).pending()


@router.get(TASK, response_model=ReviewDetail)
def task_review(project_id: str, ref: str, session: DatabaseSession) -> ReviewDetail:
    return ReviewService(session).detail(project_id, ref)


@router.post(TASK + "/decision", response_model=ReviewDetail)
def decide_review(
    project_id: str, ref: str, payload: ReviewDecision, session: DatabaseSession
) -> ReviewDetail:
    return ReviewService(session).decide(project_id, ref, payload)


@router.post(TASK + "/reopen", response_model=ReviewDetail)
def reopen_review(
    project_id: str, ref: str, payload: ReviewReopen, session: DatabaseSession
) -> ReviewDetail:
    """Take back an acceptance: the task goes back to In progress with your comment."""
    return ReviewService(session).reopen(project_id, ref, payload)


@router.post(TASK + "/follow-ups", response_model=ReviewDetail)
def make_follow_ups(
    project_id: str, ref: str, payload: FollowUpCreate, session: DatabaseSession
) -> ReviewDetail:
    """Make tasks from lines of the review: what was not done, or an unmet criterion."""
    return ReviewService(session).follow_ups(project_id, ref, payload)


@router.post(TASK + "/files", response_model=ReviewFileRead, status_code=status.HTTP_201_CREATED)
async def attach_feedback(
    project_id: str,
    ref: str,
    request: Request,
    session: DatabaseSession,
    filename: Annotated[str | None, Query(max_length=255)] = None,
) -> ReviewFileRead:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_REVIEW_FILE_BYTES:
        raise invalid(TOO_BIG)
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_REVIEW_FILE_BYTES:
            raise invalid(TOO_BIG)
    return ReviewService(session).add_feedback(project_id, ref, bytes(data), filename)


@router.get(TASK + "/fix-prompt")
def review_fix_prompt(
    project_id: str,
    ref: str,
    session: DatabaseSession,
    agent: Annotated[Literal["claude", "codex"] | None, Query()] = None,
) -> dict:
    """A prompt that hands the person's comments (or their answer to its question) back to an
    agent, and the link that opens it unsent in the agent's desktop app."""
    project = ProjectService(session).get(project_id)
    chosen = agent or get_agent_settings(session).default_agent
    return fix_prompt(session, project, ref, chosen)


@router.get("/projects/{project_id}/review-files/{file_id}", response_class=Response)
def review_file(project_id: str, file_id: str, session: DatabaseSession) -> Response:
    row = ReviewService(session).get_file(project_id, file_id)
    media_type = row.media_type + ("; charset=utf-8" if row.media_type == "text/plain" else "")
    return Response(
        row.data,
        media_type=media_type,
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete(
    "/projects/{project_id}/review-files/{file_id}", status_code=status.HTTP_204_NO_CONTENT
)
def remove_review_file(project_id: str, file_id: str, session: DatabaseSession) -> Response:
    ReviewService(session).remove_file(project_id, file_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

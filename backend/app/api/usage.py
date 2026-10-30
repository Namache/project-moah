"""Live token and time use by Claude Code and Codex from their local logs. Counts, never text."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.services.usage import UsageReader, usage_summary

router = APIRouter(prefix="/api/usage", tags=["usage"])
DatabaseSession = Annotated[Session, Depends(get_session)]


def get_reader(request: Request) -> UsageReader:
    state = request.app.state
    if getattr(state, "usage_reader", None) is None:
        state.usage_reader = UsageReader()
    return state.usage_reader


# A plain function so the log scan runs in the thread pool instead of blocking the event loop.
@router.get("")
def get_usage(
    session: DatabaseSession,
    reader: Annotated[UsageReader, Depends(get_reader)],
    since: Annotated[datetime | None, Query(description="Start; defaults to 7 days ago")] = None,
    until: Annotated[datetime | None, Query(description="End; defaults to now")] = None,
    agent: Annotated[Literal["claude", "codex"] | None, Query()] = None,
    tz_offset: Annotated[int, Query(ge=-840, le=840, description="Minutes east of UTC")] = 0,
    bucket: Annotated[Literal["hour", "day"], Query()] = "day",
) -> dict[str, Any]:
    now = datetime.now(UTC)
    start = since or now - timedelta(days=7)
    if start.tzinfo is None or (until is not None and until.tzinfo is None):
        raise HTTPException(status_code=422, detail="Give times with a time zone.")
    return usage_summary(
        session,
        reader,
        start,
        now,
        until=until,
        agent=agent,
        tz_offset_minutes=tz_offset,
        bucket=bucket,
    )

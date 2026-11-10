"""Reviews as the MCP server handles them: screenshots an agent attaches, and the latest round."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.exc import UnboundExecutionError
from sqlalchemy.orm import Session, sessionmaker

from app.services.reviews import ANSWERED_IN_CHAT, ReviewService, Screenshot

# Finished work always reaches the person: a task moved to review without the agent's report
# gets one Moah drafts from its checkpoints, and the agent is asked for a better one. (Refusing
# the move kept finished work out of Review, since agents seldom write the report.)
REVIEW_DRAFTED = (
    "{task} waits in the person's Review screen with a report Moah drafted from your "
    'checkpoints. Write a better one now with brain_submit_review(task="{task}", summary, done, '
    "not_done, how_to_check, screenshots): it replaces the draft. Writing it needs no "
    "permission. Finished several tasks? Submit one review for each."
)

TEXT_ATTACHMENT_LIMIT = 4000


def review_drop_folder(session: Session) -> Path | None:
    """Where agents save screenshots when this server runs in the Flatpak sandbox, which can
    read only its own data folder. None outside the sandbox: any path works there."""
    if not Path("/.flatpak-info").exists():
        return None
    try:
        database = session.get_bind().url.database
    except UnboundExecutionError:  # a server built only to count its tools has no database
        return None
    if not database:
        return None
    return Path(database).resolve().parent / "review-files"


def review_drop_folder_for(session_factory: sessionmaker[Session]) -> Path | None:
    with session_factory() as session:
        return review_drop_folder(session)


def read_screenshots(
    paths: list[str], captions: list[str] | None, drop: Path | None
) -> list[Screenshot]:
    """The screenshot files an agent named, read from disk. Relative paths start at the folder
    this server runs in, which is the agent's working folder."""
    from app.models.review import MAX_REVIEW_FILE_BYTES

    hint = (
        f" This Project Moah runs in a Flatpak sandbox and reads screenshots only from {drop}:"
        " save or copy them there and pass those paths."
        if drop is not None
        else ""
    )
    shots = []
    for index, raw in enumerate(paths):
        path = Path(raw.strip()).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        try:
            if not path.is_file():
                raise ValueError(f"No screenshot file at {raw}.{hint}")
            if path.stat().st_size > MAX_REVIEW_FILE_BYTES:
                raise ValueError(f"{raw} is over 5 MB: save a smaller PNG or a JPEG.")
            data = path.read_bytes()
        except OSError:
            raise ValueError(f"Project Moah can't read {raw}.{hint}") from None
        caption = captions[index] if captions and index < len(captions) else None
        shots.append(Screenshot(data=data, filename=path.name, caption=caption))
    return shots


def clear_dropped(paths: list[str], drop: Path | None) -> None:
    """Screenshots saved in the drop folder are in the database now: remove the copies."""
    if drop is None:
        return
    for raw in paths:
        path = Path(raw.strip()).expanduser()
        try:
            if path.resolve().parent == drop.resolve():
                path.unlink(missing_ok=True)
        except OSError:
            pass


def review_for_agent(session: Session, task_id: str) -> dict:
    """The latest review round of a task, as an agent needs it: the person's verdict, comment
    and attachments (text files inline, pictures through brain_view_images)."""
    reviews = ReviewService(session)
    latest = reviews.latest(task_id)
    if latest is None:
        return {}
    question = latest.kind == "question"
    state = {
        "pending": f"waiting for the person's {'answer' if question else 'review'}",
        "accepted": "accepted by the person",
        "rejected": "sent back by the person: fix what the comment asks, then submit again",
        "answered": "answered by the person: go on with the task using their answer",
    }[latest.status]
    if latest.moved_to == ANSWERED_IN_CHAT:
        state = "answered by the person in the chat: go on with the task using their answer"
    elif latest.moved_to and not latest.comment:
        state = f"{state.split(':')[0]} by moving the task to {latest.moved_to} on the board"
    review: dict[str, Any] = {
        "round": latest.round,
        "status": state,
        "submitted_by": latest.agent,
        "question" if question else "summary": latest.summary,
    }
    if question and latest.options:
        review["options"] = list(latest.options)
    if latest.status != "pending":
        review["comment"] = latest.comment or ""
        files = reviews.feedback_files(latest.id)
        if files:
            review["attachments"] = []
            for row in files:
                entry: dict[str, Any] = {"id": row.id, "filename": row.filename}
                if row.media_type == "text/plain":
                    text = row.data.decode("utf-8", errors="replace")
                    if len(text) > TEXT_ATTACHMENT_LIMIT:
                        text = text[:TEXT_ATTACHMENT_LIMIT] + "\n[cut]"
                    entry["text"] = text
                else:
                    entry["view"] = f'brain_view_images(record="{row.id}")'
                review["attachments"].append(entry)
    return {"review": review}

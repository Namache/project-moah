"""What the person decided in Review, handed to the chat that asked or reported.

An agent asks in its chat and the question waits in Review; the person answers there, or sends a
report back with comments. Each such review remembers the chat that wrote it
(``TaskReview.session_id``), and this module is how the decision gets back to that chat:

- ``undelivered`` finds the decisions of a chat that nobody handed over yet: an answer (a picked
  option and "go on as planned" included), a send-back (comments, and the files that came with
  them), also of accepted work the person reopened, and an acceptance that came with a comment or
  a file. Accepting with neither wakes nobody. An answer the person gave in the chat itself is
  not one: the agent has it.
- ``deliver`` claims them (``delivered_at``, one atomic update per decision, so a waiter and the
  prompt hook never both hand the same one over), writes one message with ``delivery_text`` and
  gives the claim back when the message could not be written.
- The Stop hook's waiter (services/chat_wait.py) calls ``deliver`` the moment a decision exists,
  and wakes the chat with the text. When no waiter ran (the app was closed, a day passed), the
  prompt hook does it when the person next writes in that chat (``prompt_delivery``).

The message starts with a fixed line (DELIVERY_MARKER), so a hook can tell it from the person's
own words, and ends with the ids of the decisions it carries.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.orm import Session, aliased

from app.models.review import ReviewFile, TaskReview
from app.models.task import Task
from app.services.chat_wait import (
    DELIVERABLE_STATUSES,
    DELIVERY_WINDOW,
    SETTLE,
    write_stderr,
    write_stdout,
)
from app.services.hook_text import valid_id
from app.services.reviews import ANSWERED_IN_CHAT, APPROVED, one_line

DELIVERY_MARKER = "Project Moah Review: the person decided in Review."
IDS_PREFIX = "(Moah review ids: "
IDS_LINE = re.compile(r"^\(Moah review ids: ([^)]*)\)\s*$", re.MULTILINE)
TASK_NOTIFICATION = "<task-notification>"  # what starts a message Claude Code sends by itself
MAX_ITEMS = 8  # decisions in one message; the rest go in the next
TITLE_LIMIT = 120
SUMMARY_LIMIT = 240
COMMENT_LIMIT = 3000
ANSWER_NEXT = (
    "Next: carry on with the task using this answer. Do not ask it again: it is already"
    " recorded in Moah."
)
APPROVED_NEXT = "Next: carry on with the task as planned."
SEND_BACK_NEXT = (
    "Next: work on these comments, then hand the task over again with brain_submit_review."
)
ACCEPTED_NEXT = (
    "Next: the task is done. If {asks} for more work, record it as a new task"
    " (brain_create_task) and do it there; otherwise just acknowledge it briefly."
)
FILES_NOTE = (
    "Files attached to the comments: {count}. Read them with brain_get_task (text files) and"
    " brain_view_images (pictures)."
)

Write = Callable[[str], None]


def _aware(at: datetime) -> datetime:
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def undelivered(session: Session, session_id: str, now: datetime | None = None) -> list[TaskReview]:
    """The decisions of this chat that were not handed over, oldest first (decided in the last
    DELIVERY_WINDOW). chat_wait.DELIVERABLE says the same in SQL for the waiter."""
    now = _aware(now or datetime.now(UTC))
    newer = aliased(TaskReview)
    has_words = or_(
        TaskReview.comment.is_not(None),
        exists().where(ReviewFile.review_id == TaskReview.id, ReviewFile.kind == "feedback"),
    )
    return list(
        session.scalars(
            select(TaskReview)
            .where(
                TaskReview.session_id == session_id,
                TaskReview.status.in_(DELIVERABLE_STATUSES),
                or_(TaskReview.moved_to.is_(None), TaskReview.moved_to != ANSWERED_IN_CHAT),
                TaskReview.delivered_at.is_(None),
                TaskReview.reviewed_at >= now - DELIVERY_WINDOW,
                has_words,
                ~exists().where(
                    newer.task_id == TaskReview.task_id, newer.round > TaskReview.round
                ),
            )
            .order_by(TaskReview.reviewed_at, TaskReview.round)
            .execution_options(populate_existing=True)
        )
    )


def claim(session: Session, reviews: list[TaskReview], now: datetime) -> list[TaskReview]:
    """Mark each decision as handed over, and keep the ones this call marked. Another process
    that got to one first has it: its update finds ``delivered_at`` set and changes nothing."""
    claimed = []
    for review in reviews:
        done = session.execute(
            update(TaskReview)
            .where(TaskReview.id == review.id, TaskReview.delivered_at.is_(None))
            .values(delivered_at=now)
        )
        if done.rowcount == 1:
            claimed.append(review)
    session.commit()
    return claimed


def release(session: Session, reviews: list[TaskReview], claimed_at: datetime) -> None:
    """Take a claim back, because the message did not get out. Only this call's own claim: a
    decision another process claimed since keeps its mark."""
    session.rollback()
    if reviews:
        session.execute(
            update(TaskReview)
            .where(
                TaskReview.id.in_([review.id for review in reviews]),
                TaskReview.delivered_at == claimed_at,
            )
            .values(delivered_at=None)
        )
    session.commit()


def _cut(text: str) -> str:
    text = text.strip()
    if len(text) <= COMMENT_LIMIT:
        return text
    return text[: COMMENT_LIMIT - 1].rstrip() + "… (cut: the whole text is in Moah)"


def _item(task: Task | None, review: TaskReview, files: int) -> str:
    """One decision: the task, what the agent wrote, what the person decided, and what to do."""
    name = f'{task.human_id} "{one_line(task.title, TITLE_LIMIT)}"' if task else "A task"
    asked = review.kind == "question"
    summary = one_line(review.summary, SUMMARY_LIMIT)
    lines = [name, f"You asked: {summary}" if asked else f"You handed over: {summary}"]
    said = (review.comment or "").strip()
    if review.status == "accepted":
        # Finished work, or the agent's note taken as finished work, moved to Done with words.
        ref = task.human_id if task else "the task"
        what = "your note" if review.checkpoint_id else "your question" if asked else "it"
        lines.append(
            f"The person accepted {what} and moved {ref} to Done, "
            + (f"with this comment: {_cut(said)}" if said else "with files and no words.")
        )
        asks = "the files ask"
        if said:
            asks = "the comment or the files ask" if files else "the comment asks"
        next_step = ACCEPTED_NEXT.format(asks=asks)
    elif review.status == "answered":
        if said == APPROVED:
            lines.append("The person approved: go on as planned.")
            next_step = APPROVED_NEXT
        else:
            picked = bool(review.options) and said in review.options
            if said:
                lines.append(f"The person {'chose' if picked else 'answered'}: {_cut(said)}")
            next_step = ANSWER_NEXT
    else:
        if said:
            lines.append(f"The person sent it back with comments: {_cut(said)}")
        else:
            lines.append("The person sent it back, with files and no words.")
        next_step = SEND_BACK_NEXT
    if files:
        lines.append(FILES_NOTE.format(count=files))
    lines.append(next_step)
    return "\n".join(lines)


def delivery_text(session: Session, reviews: list[TaskReview]) -> str:
    """One plain message for all of these decisions: the marker line, each decision (see _item),
    and the ids of the reviews as the last line. English, short, no tables, no file paths."""
    ids = [review.id for review in reviews]
    counts = dict(
        session.execute(
            select(ReviewFile.review_id, func.count(ReviewFile.id))
            .where(ReviewFile.review_id.in_(ids), ReviewFile.kind == "feedback")
            .group_by(ReviewFile.review_id)
        ).all()
    )
    items = [
        _item(session.get(Task, review.task_id), review, counts.get(review.id, 0))
        for review in reviews
    ]
    return "\n\n".join([DELIVERY_MARKER, *items, f"{IDS_PREFIX}{', '.join(ids)})"])


def is_delivery(text: object) -> bool:
    """Whether a message is one of these: the person did not write it, Moah handed it over.

    Codex's queue sends the text as it is, so the marker starts it. Claude Code does not: a hook
    that wakes the chat reaches the prompt hook as a message of its own (seen in Claude Code
    2.1.330), the text wrapped as ``<task-notification>...</task-notification><system-reminder>Stop
    hook blocking error from command "Stop": <the text></system-reminder>``. So the marker is also
    taken anywhere in the message when the line with the review ids, which ends every delivery, is
    there too: nobody types both by accident."""
    if not isinstance(text, str):
        return False
    return text.lstrip().startswith(DELIVERY_MARKER) or (
        DELIVERY_MARKER in text and IDS_LINE.search(text) is not None
    )


def is_task_notification(text: object) -> bool:
    """Whether Claude Code, not the person, sent this message: it starts with a task notification.

    Claude Code hands the chat a message of that shape when something it ran in the background
    finishes, and when a hook wakes the chat (any hook's, not only Moah's: is_delivery knows
    Moah's own text). Either way these are not the person's words, so the prompt hook must not take
    one for the reply to a question."""
    return isinstance(text, str) and text.lstrip().startswith(TASK_NOTIFICATION)


def delivery_ids(text: str) -> list[str]:
    """The review ids a delivery message names on its last line."""
    found = IDS_LINE.findall(text)
    return [item.strip() for item in found[-1].split(",") if item.strip()] if found else []


def deliver(session: Session, session_id: str, write: Write, now: datetime | None = None) -> bool:
    """Hand this chat its undelivered decisions in one message through ``write``. True when it
    did. The decisions are claimed before the message is written, so two callers never both send
    one; when writing fails (or anything else does), the claim is taken back and the error goes
    on to the caller. False when there was nothing left to hand over, or another caller did."""
    now = _aware(now or datetime.now(UTC))
    found = undelivered(session, session_id, now)[:MAX_ITEMS]
    claimed = claim(session, found, now) if found else []
    if not claimed:
        return False
    try:
        write(delivery_text(session, claimed))
    except BaseException:
        release(session, claimed, now)
        raise
    return True


def prompt_delivery(
    session: Session,
    agent: str,
    hook_input: Mapping[str, object],
    *,
    wake: bool = False,
    sleep: Callable[[float], None] | None = None,
    settle: float | None = None,
) -> int:
    """The prompt hook's fallback, for a chat whose waiter did not hand a decision over (it was
    never started, or ended): when the person writes in the chat, give it what they decided in
    Review. Returns the hook's exit code.

    Claude Code, only with ``wake`` (the hook line Connect writes with ``--deliver``, run in the
    background in a way that lets exit code 2 reach the chat: from a plain background hook it is
    lost after the claim): after SETTLE seconds, so a waiter that is still there goes first, the
    message goes to standard error and the exit code is 2, which Claude Code shows the chat as a
    system reminder. Codex: plain standard output of this hook is added to the model's context;
    no wait, the hook is not in the background, and the code is 0, with no flag. Nothing for
    another agent, and 0 whenever nothing was handed over: only a delivery ever returns 2."""
    session_id = valid_id(hook_input.get("session_id"))
    if session_id is None or agent not in ("claude", "codex") or (agent == "claude" and not wake):
        return 0
    if not undelivered(session, session_id):
        return 0
    if agent == "claude":
        (sleep or time.sleep)(SETTLE if settle is None else settle)
        return 2 if deliver(session, session_id, write_stderr) else 0
    deliver(session, session_id, write_stdout)
    return 0

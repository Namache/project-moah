"""Reviews of finished work: agents submit them, the person accepts or sends them back.

A task is in review while its status is review. Its review is the newest pending round; when an
agent moved the task to review without writing one, Moah shows one drafted from the task's latest
checkpoint and stores it only when the person acts on it. Accepting moves the task to Done.
Sending it back needs a comment and returns the task to in progress, where the next agent's brief
shows it.
Moving the task out of review on the board settles its report too (see TaskService).

An agent that cannot go on without the person asks a question: the task moves to Blocked and the
question waits in Review (first, since work is stuck on it) until the person answers. The answer
goes back like a send-back. A task an agent blocked without asking shows its checkpoint instead.
Lines the person wants kept (what was not done, unmet criteria) become follow-up tasks.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, undefer

from app.models.checkpoint import ActivityEvent, Checkpoint
from app.models.project import Project, utc_now
from app.models.proposal import Proposal
from app.models.review import (
    MAX_FILES_PER_KIND,
    MAX_REVIEW_FILE_BYTES,
    MAX_TEXT_FILE_BYTES,
    TEXT_FILE_TYPE,
    ReviewFile,
    TaskReview,
)
from app.models.task import AcceptanceCriterion, Task
from app.schemas.review import (
    AskPerson,
    CriterionTick,
    FollowUp,
    FollowUpCreate,
    PendingReviewItem,
    PendingReviews,
    ReviewCriterion,
    ReviewDecision,
    ReviewDetail,
    ReviewFileRead,
    ReviewItem,
    ReviewRound,
    ReviewSubmit,
    ReviewTimeline,
)
from app.schemas.task import RelationshipCreate, TaskCreate, TaskUpdate
from app.services.activity import ActivityService, current_actor
from app.services.errors import conflict, invalid, not_found
from app.services.images import clean_filename, sniff
from app.services.projects import ProjectService
from app.services.tasks import TaskService

WAITING_STATUS = "review"
QUESTION_STATUS = "blocked"  # where a task waits while an agent's question waits for an answer
CLOSED = ("completed", "archived")
TITLE_LIMIT = 200
REVIEWED_LIMIT = 80
NEWEST_PENDING = 5
SUMMARY_LINE = 240
BULLET = re.compile(r"^\s*(?:[-*•+]|\d+[.)])\s+")


@dataclass
class Screenshot:
    data: bytes
    filename: str
    caption: str | None = None


def _lines(text: str | None) -> list[str]:
    """Checkpoint text as list items: one per line, bullets and numbers removed."""
    items = []
    for line in (text or "").splitlines():
        line = BULLET.sub("", line).strip()
        if line:
            items.append(line)
    return items


def _one_line(text: str, limit: int = SUMMARY_LINE) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def file_type(data: bytes, *, images_only: bool) -> tuple[str, int | None, int | None]:
    """The stored type of an attached file: an image (from its header), or plain text."""
    try:
        return sniff(data)
    except Exception:  # noqa: BLE001 - not an image; maybe text
        if images_only:
            raise invalid("Screenshots must be PNG, JPEG, WebP or GIF images") from None
    if len(data) > MAX_TEXT_FILE_BYTES or b"\x00" in data:
        raise invalid(
            "Only images (PNG, JPEG, WebP, GIF) and text files up to 1 MB can be attached"
        )
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        raise invalid(
            "Only images (PNG, JPEG, WebP, GIF) and text files up to 1 MB can be attached"
        ) from None
    return TEXT_FILE_TYPE, None, None


class ReviewService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.tasks = TaskService(session)
        self.projects = ProjectService(session)

    # ---- agent side --------------------------------------------------------------------

    def submit(
        self,
        project_id: str,
        task_ref: str,
        payload: ReviewSubmit,
        agent: str,
        screenshots: Iterable[Screenshot] = (),
    ) -> TaskReview:
        """Store a new round of the task's review and move the task to review."""
        task = self.tasks.get(project_id, task_ref)
        if task.status == "archived":
            raise conflict(f"{task.human_id} is archived. Ask the person to restore it first.")
        shots = list(screenshots)
        if len(shots) > MAX_FILES_PER_KIND:
            raise invalid(f"Attach at most {MAX_FILES_PER_KIND} screenshots")
        checked = []
        for shot in shots:
            if not shot.data:
                raise invalid(f"{shot.filename} is empty")
            if len(shot.data) > MAX_REVIEW_FILE_BYTES:
                raise invalid(f"{shot.filename} is over {MAX_REVIEW_FILE_BYTES // 2**20} MB")
            checked.append((shot, *file_type(shot.data, images_only=True)))
        self._replace_pending(task)
        review = TaskReview(
            project_id=project_id,
            task_id=task.id,
            round=self._next_round(task.id),
            agent=agent,
            status="pending",
            summary=payload.summary,
            done=payload.done,
            not_done=payload.not_done,
            how_to_check=payload.how_to_check,
            details=payload.details,
            generated=False,
        )
        self.session.add(review)
        self.session.flush()
        for order, (shot, media_type, width, height) in enumerate(checked):
            self.session.add(
                ReviewFile(
                    project_id=project_id,
                    review_id=review.id,
                    kind="screenshot",
                    filename=clean_filename(shot.filename, media_type),
                    media_type=media_type,
                    size_bytes=len(shot.data),
                    width=width,
                    height=height,
                    caption=(shot.caption or "").strip() or None,
                    sort_order=order,
                    data=shot.data,
                    created_by=agent,
                )
            )
        self._log(task, "REVIEW_SUBMITTED", review, screenshots=len(checked))
        self._to_review(task)
        return review

    def ask(self, project_id: str, task_ref: str, payload: AskPerson, agent: str) -> TaskReview:
        """Store an agent's question for the person and move the task to Blocked, where it
        waits in Review until they answer."""
        task = self.tasks.get(project_id, task_ref)
        if task.status in CLOSED:
            raise conflict(f"{task.human_id} is {task.status}. Ask about an open task.")
        self._replace_pending(task)
        review = TaskReview(
            project_id=project_id,
            task_id=task.id,
            round=self._next_round(task.id),
            agent=agent,
            kind="question",
            status="pending",
            summary=payload.question,
            done=[],
            not_done=[],
            how_to_check=None,
            details=payload.context,
            options=payload.options or None,
            generated=False,
        )
        self.session.add(review)
        self.session.flush()
        self._log(task, "QUESTION_ASKED", review)
        if task.status != QUESTION_STATUS:
            self.tasks.update(project_id, task.id, TaskUpdate(status=QUESTION_STATUS))
        else:
            self.session.commit()
        return review

    def asked_question(self, task_id: str) -> TaskReview | None:
        """The agent's question still waiting for the person, if any."""
        return self._pending(task_id, "question")

    def submitted_review(self, task_id: str) -> TaskReview | None:
        """The pending report the agent wrote itself, if any."""
        return self.session.scalar(
            select(TaskReview).where(
                TaskReview.task_id == task_id,
                TaskReview.status == "pending",
                TaskReview.kind == "work",
                TaskReview.generated.is_(False),
            )
        )

    # ---- reading -----------------------------------------------------------------------

    def timeline(self, project_id: str | None = None, reviewed_limit: int = REVIEWED_LIMIT):
        projects = self._projects()
        waiting = self._waiting_tasks(project_id, projects) + self._waiting_suggestions(
            project_id, projects
        )
        # Questions first: work is stuck until the person answers them.
        waiting.sort(key=lambda item: (item.question, item.done_at), reverse=True)
        reviewed = self._reviewed_tasks(project_id, projects, reviewed_limit)
        reviewed += self._reviewed_suggestions(project_id, projects, reviewed_limit)
        reviewed.sort(key=lambda item: item.reviewed_at or item.done_at, reverse=True)
        return ReviewTimeline(waiting=waiting, reviewed=reviewed[:reviewed_limit])

    def pending(self) -> PendingReviews:
        items = self.timeline(reviewed_limit=1).waiting
        by_project: dict[str, int] = {}
        for item in items:
            by_project[item.project_id] = by_project.get(item.project_id, 0) + 1
        return PendingReviews(
            total=len(items),
            by_project=by_project,
            newest=[
                PendingReviewItem(
                    key=item.key,
                    kind=item.kind,
                    project_name=item.project_name,
                    agent=item.agent,
                    title=item.title,
                    question=item.question,
                )
                for item in items[:NEWEST_PENDING]
            ],
        )

    def waiting_count(self, project_id: str) -> int:
        return self.session.scalar(
            select(func.count(Task.id)).where(
                Task.project_id == project_id, Task.status == WAITING_STATUS
            )
        )

    def question_count(self, project_id: str) -> int:
        return self.session.scalar(
            select(func.count(TaskReview.id))
            .join(Task, Task.id == TaskReview.task_id)
            .where(
                TaskReview.project_id == project_id,
                TaskReview.status == "pending",
                TaskReview.kind == "question",
                Task.status == QUESTION_STATUS,
            )
        )

    def detail(self, project_id: str, task_ref: str) -> ReviewDetail:
        task = self.tasks.get(project_id, task_ref)
        project = self.projects.get(project_id)
        rounds = list(
            self.session.scalars(
                select(TaskReview)
                .where(TaskReview.task_id == task.id)
                .order_by(TaskReview.round.desc())
            )
        )
        pending = next((r for r in rounds if r.status == "pending"), None)
        if pending is not None:
            current = pending
        elif self._waits_for(task) is not None:
            current = self._draft(task)
        elif rounds:
            current = rounds[0]
        else:
            raise not_found(f"{task.human_id} has no review yet")
        files = self._files([r.id for r in rounds])
        earlier = [r for r in rounds if r is not current and r.status != "replaced"]
        return ReviewDetail(
            project_id=project.id,
            project_name=project.name,
            project_slug=project.slug,
            task_id=task.id,
            task_ref=task.human_id,
            task_title=task.title,
            task_status=task.status,
            task_description=task.description,
            criteria=[
                ReviewCriterion(id=c.id, description=c.description, is_completed=c.is_completed)
                for c in task.criteria
            ],
            current=self._round(current, files),
            earlier=[self._round(r, files) for r in earlier],
        )

    def waits_for(self, task: Task) -> str | None:
        """What the task waits for in Review: "work" to review, a "question" to answer, or
        None."""
        return self._waits_for(task)

    def latest(self, task_id: str) -> TaskReview | None:
        return self.session.scalar(
            select(TaskReview)
            .where(TaskReview.task_id == task_id, TaskReview.status != "replaced")
            .order_by(TaskReview.round.desc())
            .limit(1)
        )

    def feedback_files(self, review_id: str) -> list[ReviewFile]:
        return list(
            self.session.scalars(
                select(ReviewFile)
                .options(undefer(ReviewFile.data))
                .where(ReviewFile.review_id == review_id, ReviewFile.kind == "feedback")
                .order_by(ReviewFile.sort_order, ReviewFile.created_at)
            )
        )

    def sent_back(
        self, project_id: str, limit: int = 3, status: str = "rejected"
    ) -> list[tuple[Task, TaskReview, int]]:
        """Tasks the person sent back (or, with status answered, whose question they answered)
        that nobody has handed over again yet, newest first, with how many files came with the
        comment."""
        rows = self.session.execute(
            select(Task, TaskReview)
            .join(TaskReview, TaskReview.task_id == Task.id)
            .where(
                Task.project_id == project_id,
                Task.status.not_in((WAITING_STATUS, *CLOSED)),
                TaskReview.status == status,
            )
            .order_by(TaskReview.reviewed_at.desc())
        ).all()
        found: list[tuple[Task, TaskReview, int]] = []
        seen: set[str] = set()
        for task, review in rows:
            if task.id in seen:
                continue
            seen.add(task.id)
            if self.latest(task.id) is not review:
                continue  # a newer round exists
            count = self.session.scalar(
                select(func.count(ReviewFile.id)).where(
                    ReviewFile.review_id == review.id, ReviewFile.kind == "feedback"
                )
            )
            if review.moved_to and not review.comment and not count:
                continue  # dragged back on the board: nothing for the agent to read
            found.append((task, review, count))
            if len(found) >= limit:
                break
        return found

    def get_file(self, project_id: str, file_id: str) -> ReviewFile:
        row = self.session.scalar(
            select(ReviewFile)
            .options(undefer(ReviewFile.data))
            .where(ReviewFile.project_id == project_id, ReviewFile.id == file_id)
        )
        if row is None:
            raise not_found("File not found in this project")
        return row

    def find_file(self, file_id: str) -> ReviewFile | None:
        return self.session.scalar(
            select(ReviewFile).options(undefer(ReviewFile.data)).where(ReviewFile.id == file_id)
        )

    # ---- person side -------------------------------------------------------------------

    def add_feedback(
        self, project_id: str, task_ref: str, data: bytes, filename: str | None
    ) -> ReviewFileRead:
        task, _ = self._waiting(project_id, task_ref)
        if not data:
            raise invalid("The file is empty")
        if len(data) > MAX_REVIEW_FILE_BYTES:
            raise invalid(f"Files can be at most {MAX_REVIEW_FILE_BYTES // 2**20} MB")
        media_type, width, height = file_type(data, images_only=False)
        review = self._stored_pending(task)
        count = self.session.scalar(
            select(func.count(ReviewFile.id)).where(
                ReviewFile.review_id == review.id, ReviewFile.kind == "feedback"
            )
        )
        if count >= MAX_FILES_PER_KIND:
            raise invalid(f"Attach at most {MAX_FILES_PER_KIND} files to one comment")
        actor_type, actor_name = current_actor()
        name = (
            clean_filename(filename, media_type)
            if media_type != TEXT_FILE_TYPE
            else (
                " ".join((filename or "").replace("/", " ").replace("\\", " ").split())[:200]
                or "note.txt"
            )
        )
        row = ReviewFile(
            project_id=project_id,
            review_id=review.id,
            kind="feedback",
            filename=name,
            media_type=media_type,
            size_bytes=len(data),
            width=width,
            height=height,
            sort_order=count,
            data=data,
            created_by=actor_name or actor_type,
        )
        self.session.add(row)
        self.session.commit()
        return ReviewFileRead.model_validate(row)

    def remove_file(self, project_id: str, file_id: str) -> None:
        row = self.get_file(project_id, file_id)
        review = self.session.get(TaskReview, row.review_id)
        if row.kind != "feedback" or review is None or review.status != "pending":
            raise conflict("Only files you attached to a comment you have not sent can be removed")
        self.session.delete(row)
        self.session.commit()

    def decide(self, project_id: str, task_ref: str, decision: ReviewDecision) -> ReviewDetail:
        task, waits = self._waiting(project_id, task_ref)
        answering = decision.verdict == "answer"
        if answering != (waits == "question"):
            raise conflict(
                f"{task.human_id} waits for your answer, not a review"
                if waits == "question"
                else f"{task.human_id} has no question waiting"
            )
        comment = (decision.comment or "").strip() or None
        review = self._stored_pending(task)
        if decision.verdict != "accept" and comment is None:
            has_files = self.session.scalar(
                select(func.count(ReviewFile.id)).where(
                    ReviewFile.review_id == review.id, ReviewFile.kind == "feedback"
                )
            )
            if not has_files:
                raise invalid(
                    "Write your answer for the agent"
                    if answering
                    else "Say what should change, so the agent knows what to fix"
                )
        now = utc_now()
        review.status = {"accept": "accepted", "reject": "rejected", "answer": "answered"}[
            decision.verdict
        ]
        review.comment = comment
        review.reviewed_at = now
        event = "QUESTION_ANSWERED" if answering else f"REVIEW_{review.status.upper()}"
        self._log(task, event, review, comment=_one_line(comment or "", 200))
        if not answering:
            self._tick(task, decision.criteria, only_unmet=decision.verdict == "reject", now=now)
        if decision.verdict == "accept":
            for proposal in self._completion_suggestions(task):
                proposal.status, proposal.reviewed_at = "accepted", now
                proposal.review_note = "Accepted in review."
            self.session.flush()  # so moving the task sees what was settled here
            self.tasks.update(project_id, task.id, TaskUpdate(status="completed"))
            if decision.follow_ups:
                self._make_follow_ups(task, review, decision.follow_ups, decision.follow_up_status)
        else:
            if not answering:
                for proposal in self._completion_suggestions(task):
                    proposal.status, proposal.reviewed_at = "rejected", now
                    note = "Sent back from review: " + (comment or "see the review")
                    proposal.review_note = note
            self.session.flush()
            self.tasks.update(project_id, task.id, TaskUpdate(status="in_progress"))
        return self.detail(project_id, task.id)

    def follow_ups(self, project_id: str, task_ref: str, payload: FollowUpCreate) -> ReviewDetail:
        """Make tasks from lines of the review shown for a task: what was not done, or an
        acceptance criterion that is not met. Each new task is related to this one."""
        task = self.tasks.get(project_id, task_ref)
        review = self._pending(task.id) or self.latest(task.id)
        if review is None:
            if self._waits_for(task) is None:
                raise not_found(f"{task.human_id} has no review yet")
            review = self._stored_pending(task)
        self._make_follow_ups(task, review, payload.items, payload.status)
        return self.detail(project_id, task.id)

    # ---- internals ---------------------------------------------------------------------

    def _projects(self) -> dict[str, Project]:
        return {p.id: p for p in self.session.scalars(select(Project))}

    def _waiting(self, project_id: str, task_ref: str) -> tuple[Task, str]:
        task = self.tasks.get(project_id, task_ref)
        waits = self._waits_for(task)
        if waits is None:
            raise conflict(f"{task.human_id} is not waiting for review")
        return task, waits

    def _waits_for(self, task: Task) -> str | None:
        if task.status == WAITING_STATUS:
            return "work"
        if task.status == QUESTION_STATUS and (
            self._pending(task.id, "question") is not None or self._entered(task)[2]
        ):
            return "question"
        return None

    def _pending(self, task_id: str, kind: str | None = None) -> TaskReview | None:
        statement = select(TaskReview).where(
            TaskReview.task_id == task_id, TaskReview.status == "pending"
        )
        if kind:
            statement = statement.where(TaskReview.kind == kind)
        return self.session.scalar(statement.order_by(TaskReview.round.desc()).limit(1))

    def _tick(
        self, task: Task, ticks: list[CriterionTick], *, only_unmet: bool, now: datetime
    ) -> None:
        """Record which acceptance criteria the person found met. Sending work back records
        only the ones they marked as not met: leaving a box ticked is not a check."""
        by_id = {c.id: c for c in task.criteria}
        changed = []
        for tick in ticks:
            criterion: AcceptanceCriterion | None = by_id.get(tick.id)
            if criterion is None or (only_unmet and tick.met):
                continue
            if criterion.is_completed != tick.met:
                criterion.is_completed, criterion.updated_at = tick.met, now
                changed.append(criterion.description)
        if changed:
            ActivityService(self.session).record(
                task.project_id,
                "TASK_CRITERIA_REVIEWED",
                entity_type="task",
                entity_id=task.id,
                task_id=task.id,
                metadata={"human_id": task.human_id, "title": task.title, "changed": changed},
            )

    def _make_follow_ups(
        self, task: Task, review: TaskReview, items: list[str], status: str
    ) -> list[str]:
        made_from = {entry.get("text") for entry in review.follow_ups or []}
        made: list[dict] = []
        for text in items:
            if text in made_from:
                continue
            made_from.add(text)
            cut = len(text) > TITLE_LIMIT
            title = text[: TITLE_LIMIT - 1].rstrip() + "…" if cut else text
            where = f"Left over from {task.human_id} “{task.title}” (review round {review.round})."
            created = self.tasks.create(
                task.project_id,
                TaskCreate(
                    title=title,
                    description=f"{where}\n\n{text}" if cut else where,
                    status=status,  # type: ignore[arg-type]
                ),
            )
            self.tasks.add_relationship(
                task.project_id, created.id, RelationshipCreate(type="related_to", target=task.id)
            )
            made.append({"text": text, "task_id": created.id})
        if made:
            review.follow_ups = [*(review.follow_ups or []), *made]  # a new list, so it saves
            self._log(task, "REVIEW_FOLLOW_UPS", review, tasks=len(made))
            self.session.commit()
        return [entry["task_id"] for entry in made]

    def _next_round(self, task_id: str) -> int:
        last = self.session.scalar(
            select(func.max(TaskReview.round)).where(TaskReview.task_id == task_id)
        )
        return (last or 0) + 1

    def _replace_pending(self, task: Task) -> None:
        for review in self.session.scalars(
            select(TaskReview).where(TaskReview.task_id == task.id, TaskReview.status == "pending")
        ):
            review.status = "replaced"

    def _to_review(self, task: Task) -> None:
        if task.status != WAITING_STATUS:
            self.tasks.update(task.project_id, task.id, TaskUpdate(status=WAITING_STATUS))
        else:
            self.session.commit()

    def _stored_pending(self, task: Task) -> TaskReview:
        pending = self.session.scalar(
            select(TaskReview).where(TaskReview.task_id == task.id, TaskReview.status == "pending")
        )
        if pending is not None:
            return pending
        draft = self._draft(task)
        self.session.add(draft)
        self.session.flush()
        return draft

    def _since(self, task: Task) -> datetime | None:
        """When the last round was decided: older checkpoints describe earlier work."""
        return self.session.scalar(
            select(func.max(TaskReview.reviewed_at)).where(TaskReview.task_id == task.id)
        )

    def _entered(self, task: Task) -> tuple[datetime, str | None, bool]:
        """When the task last moved to its current status, who moved it, and whether that was
        an agent."""
        events = self.session.scalars(
            select(ActivityEvent)
            .where(ActivityEvent.task_id == task.id)
            .order_by(ActivityEvent.timestamp.desc())
            .limit(30)
        )
        for event in events:
            meta = event.metadata_json or {}
            if meta.get("status") == task.status and meta.get("previous_status") != task.status:
                who = event.actor_name or (
                    event.actor_type if event.actor_type != "system" else None
                )
                by_agent = event.actor_type in ("claude", "codex") or (
                    event.actor_type == "system" and bool(event.actor_name)
                )
                return event.timestamp, who, by_agent
        return task.updated_at, None, False

    def _draft(self, task: Task) -> TaskReview:
        """A review drafted from the task's latest checkpoint, for work an agent moved to review
        (or a task it blocked) without writing one. Not stored."""
        since = self._since(task)
        statement = select(Checkpoint).where(Checkpoint.task_id == task.id)
        if since is not None:
            statement = statement.where(Checkpoint.created_at > since)
        checkpoint = self.session.scalar(
            statement.order_by(Checkpoint.created_at.desc(), Checkpoint.id.desc()).limit(1)
        )
        entered, mover, _ = self._entered(task)
        if checkpoint is not None:
            summary = checkpoint.summary.strip() or checkpoint.title
            done = _lines(checkpoint.completed_work)
            not_done = _lines(checkpoint.remaining_work) + _lines(checkpoint.problems)
            steps = checkpoint.next_steps.strip()
            details = f"**Next steps**\n\n{steps}" if steps else None
            agent = checkpoint.agent or mover or "agent"
        else:
            summary, done, not_done, details = "", [], [], None
            agent = mover or "agent"
        return TaskReview(
            id=None,
            project_id=task.project_id,
            task_id=task.id,
            round=self._next_round(task.id),
            agent=agent,
            kind="question" if task.status == QUESTION_STATUS else "work",
            status="pending",
            summary=summary,
            done=done,
            not_done=not_done,
            how_to_check=None,
            details=details,
            options=None,
            follow_ups=[],
            generated=True,
            created_at=entered,
            reviewed_at=None,
            comment=None,
        )

    def _files(self, review_ids: list[str]) -> dict[str, list[ReviewFileRead]]:
        found: dict[str, list[ReviewFileRead]] = {}
        if not review_ids:
            return found
        rows = self.session.scalars(
            select(ReviewFile)
            .where(ReviewFile.review_id.in_(review_ids))
            .order_by(ReviewFile.sort_order, ReviewFile.created_at)
        )
        for row in rows:
            found.setdefault(row.review_id, []).append(ReviewFileRead.model_validate(row))
        return found

    def _round(self, review: TaskReview, files: dict[str, list[ReviewFileRead]]) -> ReviewRound:
        own = files.get(review.id, []) if review.id else []
        entries = review.follow_ups or []
        made = (
            {
                t.id: t
                for t in self.session.scalars(
                    select(Task).where(Task.id.in_([e.get("task_id") for e in entries]))
                )
            }
            if entries
            else {}
        )
        return ReviewRound(
            id=review.id,
            round=review.round,
            agent=review.agent,
            kind=review.kind or "work",
            status=review.status,
            summary=review.summary,
            done=list(review.done or []),
            not_done=list(review.not_done or []),
            how_to_check=review.how_to_check,
            details=review.details,
            options=list(review.options or []),
            generated=review.generated,
            created_at=review.created_at,
            reviewed_at=review.reviewed_at,
            comment=review.comment,
            moved_to=review.moved_to,
            follow_ups=[
                FollowUp(
                    text=e["text"],
                    task_id=task.id,
                    task_ref=task.human_id,
                    task_status=task.status,
                )
                for e in entries
                if (task := made.get(e.get("task_id"))) is not None
            ],
            screenshots=[f for f in own if f.kind == "screenshot"],
            feedback=[f for f in own if f.kind == "feedback"],
        )

    def _completion_suggestions(self, task: Task) -> list[Proposal]:
        return list(
            self.session.scalars(
                select(Proposal).where(
                    Proposal.project_id == task.project_id,
                    Proposal.status == "pending",
                    Proposal.proposal_type == "complete_task",
                    Proposal.target_entity_id == task.id,
                )
            )
        )

    @staticmethod
    def _project_fields(project: Project) -> dict:
        return {
            "project_id": project.id,
            "project_name": project.name,
            "project_icon": project.icon,
            "project_accent": project.accent,
        }

    def _waiting_tasks(self, project_id: str | None, projects: dict[str, Project]):
        statement = (
            select(Task)
            .join(Project, Project.id == Task.project_id)
            .where(Task.status.in_((WAITING_STATUS, QUESTION_STATUS)), Project.status != "archived")
        )
        if project_id:
            statement = statement.where(Task.project_id == project_id)
        tasks = list(self.session.scalars(statement))
        pending = {
            r.task_id: r
            for r in self.session.scalars(
                select(TaskReview).where(
                    TaskReview.task_id.in_([t.id for t in tasks]), TaskReview.status == "pending"
                )
            )
        }
        # A blocked task waits for the person only when an agent blocked it: with a question,
        # or (if it skipped asking) with its last checkpoint. One the person blocked does not.
        tasks = [
            t
            for t in tasks
            if t.status == WAITING_STATUS
            or (pending.get(t.id) is not None and pending[t.id].kind == "question")
            or (t.id not in pending and self._entered(t)[2])
        ]
        counts = dict(
            self.session.execute(
                select(ReviewFile.review_id, func.count(ReviewFile.id))
                .where(
                    ReviewFile.review_id.in_([r.id for r in pending.values()]),
                    ReviewFile.kind == "screenshot",
                )
                .group_by(ReviewFile.review_id)
            ).all()
        )
        items = []
        for task in tasks:
            review = pending.get(task.id) or self._draft(task)
            items.append(
                ReviewItem(
                    kind="task",
                    key=f"task:{task.id}",
                    **self._project_fields(projects[task.project_id]),
                    ref=task.human_id,
                    title=task.title,
                    summary=_one_line(review.summary),
                    agent=review.agent,
                    done_at=review.created_at,
                    reviewed_at=None,
                    verdict=None,
                    question=task.status == QUESTION_STATUS,
                    task_status=task.status,
                    round=review.round,
                    screenshots=counts.get(review.id, 0) if review.id else 0,
                    generated=review.generated,
                )
            )
        return items

    def _reviewed_tasks(self, project_id: str | None, projects: dict[str, Project], limit: int):
        statement = (
            select(TaskReview, Task)
            .join(Task, Task.id == TaskReview.task_id)
            .where(TaskReview.status.in_(("accepted", "rejected", "answered")))
        )
        if project_id:
            statement = statement.where(TaskReview.project_id == project_id)
        rows = self.session.execute(
            statement.order_by(TaskReview.reviewed_at.desc()).limit(limit)
        ).all()
        counts = dict(
            self.session.execute(
                select(ReviewFile.review_id, func.count(ReviewFile.id))
                .where(
                    ReviewFile.review_id.in_([r.id for r, _ in rows]),
                    ReviewFile.kind == "screenshot",
                )
                .group_by(ReviewFile.review_id)
            ).all()
        )
        return [
            ReviewItem(
                kind="task",
                key=f"review:{review.id}",
                **self._project_fields(projects[task.project_id]),
                ref=task.human_id,
                title=task.title,
                summary=_one_line(review.summary),
                agent=review.agent,
                done_at=review.created_at,
                reviewed_at=review.reviewed_at,
                verdict=review.status,  # type: ignore[arg-type]
                question=review.kind == "question",
                task_status=task.status,
                moved_to=review.moved_to,
                round=review.round,
                screenshots=counts.get(review.id, 0),
                generated=review.generated,
            )
            for review, task in rows
        ]

    def _suggestions(self, project_id: str | None, statuses: tuple[str, ...], limit: int | None):
        from app.services.proposals import ProposalService

        statement = select(Proposal).where(Proposal.status.in_(statuses))
        if project_id:
            statement = statement.where(Proposal.project_id == project_id)
        order = (
            Proposal.created_at.desc() if statuses == ("pending",) else Proposal.reviewed_at.desc()
        )
        statement = statement.order_by(order)
        if limit:
            statement = statement.limit(limit)
        service = ProposalService(self.session)
        return [(p, service._read(p)) for p in self.session.scalars(statement)]

    def _suggestion_item(
        self, proposal: Proposal, read, projects: dict[str, Project]
    ) -> ReviewItem:
        from app.services.proposals import _summary

        return ReviewItem(
            kind="suggestion",
            key=f"proposal:{proposal.id}",
            **self._project_fields(projects[proposal.project_id]),
            ref=proposal.human_id,
            title=_one_line(_summary(proposal), 200),
            summary=_one_line(proposal.reason or "; ".join(read.changes)),
            agent=proposal.agent,
            done_at=proposal.created_at,
            reviewed_at=proposal.reviewed_at,
            verdict=proposal.status if proposal.status != "pending" else None,  # type: ignore[arg-type]
        )

    def _waiting_suggestions(self, project_id: str | None, projects: dict[str, Project]):
        in_review = set(self.session.scalars(select(Task.id).where(Task.status == WAITING_STATUS)))
        items = []
        for proposal, read in self._suggestions(project_id, ("pending",), None):
            project = projects.get(proposal.project_id)
            if project is None or project.status == "archived":
                continue
            if proposal.proposal_type == "complete_task" and proposal.target_entity_id in in_review:
                continue  # the task's own review covers it
            items.append(self._suggestion_item(proposal, read, projects))
        return items

    def _reviewed_suggestions(
        self, project_id: str | None, projects: dict[str, Project], limit: int
    ):
        return [
            self._suggestion_item(proposal, read, projects)
            for proposal, read in self._suggestions(project_id, ("accepted", "rejected"), limit)
            if proposal.project_id in projects
        ]

    def _log(self, task: Task, event: str, review: TaskReview, **extra) -> None:
        ActivityService(self.session).record(
            task.project_id,
            event,
            entity_type="task",
            entity_id=task.id,
            task_id=task.id,
            metadata={
                "human_id": task.human_id,
                "title": task.title,
                "round": review.round,
                "review": review.id,
                **extra,
            },
        )

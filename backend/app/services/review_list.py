"""The Review screen's lists: the work and questions waiting for the person (with the
reports Moah drafts for work handed over without one), what they already reviewed, and
proposals that wait with them. Read only: deciding happens in ReviewService."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.checkpoint import ActivityEvent, Checkpoint
from app.models.project import Project
from app.models.proposal import Proposal
from app.models.review import (
    ReviewFile,
    TaskReview,
)
from app.models.task import Task
from app.schemas.review import (
    PendingReviewItem,
    PendingReviews,
    ReviewItem,
    ReviewTimeline,
)
from app.services.review_notes import HASH, TASK_REF, WORD, task_refs
from app.services.reviews import (
    ENTERED_EVENTS,
    NOTES_LIMIT,
    QUESTION_STATUS,
    WAITING_STATUS,
    draft_from,
    entered_from,
    note_from,
    one_line,
)

REVIEWED_LIMIT = 80
NEWEST_PENDING = 5
# How far before the oldest waiting work a note may be to batch it, and how many notes count.
BATCH_LOOKBACK = timedelta(days=3)
BATCH_NOTES = 200


def _batch_title(title: str) -> str:
    """A batch note's title as the batch's name: the words before its colon when they say
    something ("Camp helper batch: CAMP-1 3784f03b, …"), without commit hashes."""
    head, colon, _ = title.partition(":")
    if colon and len(WORD.findall(TASK_REF.sub(" ", head))) >= 2:
        title = head
    title = re.sub(r"\s{2,}", " ", HASH.sub(" ", title)).strip(" ,;")
    return one_line(title, 120)


class ReviewList:
    def __init__(self, session: Session) -> None:
        self.session = session

    def timeline(self, project_id: str | None = None, reviewed_limit: int = REVIEWED_LIMIT):
        projects = self._projects()
        waiting = self._waiting_tasks(project_id, projects) + self._waiting_suggestions(
            project_id, projects
        )
        # Questions first: work is stuck until the person answers them.
        waiting.sort(key=lambda item: (item.question, item.done_at), reverse=True)
        self._mark_batches(waiting)
        waiting_ids = {item.key.removeprefix("task:") for item in waiting if item.kind == "task"}
        reviewed = self._reviewed_tasks(project_id, projects, reviewed_limit, waiting_ids)
        reviewed += self._reviewed_suggestions(project_id, projects, reviewed_limit)
        reviewed.sort(key=lambda item: item.reviewed_at or item.done_at, reverse=True)
        return ReviewTimeline(waiting=waiting, reviewed=reviewed[:reviewed_limit])

    def _mark_batches(self, waiting: list[ReviewItem]) -> None:
        """Mark finished work that one agent note covered together. Each task goes with the
        most specific recent note that names it and at least one other waiting task (in its
        title, else in its completed work); a note whose tasks went elsewhere, leaving it one,
        makes no batch."""
        work = [i for i in waiting if i.kind == "task" and not i.question]
        by_project: dict[str, dict[str, ReviewItem]] = {}
        for item in work:
            by_project.setdefault(item.project_id, {})[item.ref] = item
        for project_id, items in by_project.items():
            if len(items) < 2:
                continue
            prefixes = {ref.rsplit("-", 1)[0] for ref in items}
            since = min(i.done_at for i in items.values()) - BATCH_LOOKBACK
            notes = self.session.scalars(
                select(Checkpoint)
                .where(Checkpoint.project_id == project_id, Checkpoint.created_at >= since)
                .order_by(Checkpoint.created_at.desc())
                .limit(BATCH_NOTES)
            )
            best: dict[str, tuple[int, int, Checkpoint]] = {}
            for order, note in enumerate(notes):
                named: set[str] = set()
                for text in (note.title, note.completed_work):
                    named = {r for p in prefixes for r in task_refs(text, p)} & items.keys()
                    if len(named) >= 2:
                        break
                if len(named) < 2:
                    continue
                for ref in named:
                    rank = (len(named), order)
                    if ref not in best or rank < best[ref][:2]:
                        best[ref] = (*rank, note)
            groups: dict[str, list[str]] = {}
            for ref, (_, _, note) in best.items():
                groups.setdefault(note.id, []).append(ref)
            for note_id, refs in groups.items():
                if len(refs) < 2:
                    continue
                title = _batch_title(best[refs[0]][2].title)
                for ref in refs:
                    items[ref].batch, items[ref].batch_title = f"batch:{note_id}", title

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

    def _projects(self) -> dict[str, Project]:
        return {p.id: p for p in self.session.scalars(select(Project))}

    def _drafts(self, tasks: list[Task]) -> dict[str, TaskReview]:
        """The timeline's drafts for many waiting tasks at once: the same as ``_draft(task,
        named=False)`` for each, in five queries instead of four per task."""
        if not tasks:
            return {}
        ids = [t.id for t in tasks]
        last_any: dict[str, datetime] = {}
        last_work: dict[str, datetime] = {}
        last_round: dict[str, int] = {}
        for at in range(0, len(ids), 500):
            chunk = ids[at : at + 500]
            for task_id, kind, reviewed_at, round_ in self.session.execute(
                select(
                    TaskReview.task_id,
                    TaskReview.kind,
                    func.max(TaskReview.reviewed_at),
                    func.max(TaskReview.round),
                )
                .where(TaskReview.task_id.in_(chunk))
                .group_by(TaskReview.task_id, TaskReview.kind)
            ):
                last_round[task_id] = max(last_round.get(task_id, 0), round_ or 0)
                if reviewed_at is not None:
                    if task_id not in last_any or reviewed_at > last_any[task_id]:
                        last_any[task_id] = reviewed_at
                    if kind == "work":
                        last_work[task_id] = reviewed_at
        events: dict[str, list[ActivityEvent]] = {}
        notes: dict[str, list[Checkpoint]] = {}
        for at in range(0, len(ids), 500):
            chunk = ids[at : at + 500]
            ranked = (
                select(
                    ActivityEvent.id,
                    func.row_number()
                    .over(
                        partition_by=ActivityEvent.task_id,
                        order_by=(ActivityEvent.timestamp.desc(), ActivityEvent.id.desc()),
                    )
                    .label("n"),
                )
                .where(ActivityEvent.task_id.in_(chunk))
                .subquery()
            )
            for event in self.session.scalars(
                select(ActivityEvent)
                .join(ranked, ranked.c.id == ActivityEvent.id)
                .where(ranked.c.n <= ENTERED_EVENTS)
                .order_by(ActivityEvent.timestamp.desc(), ActivityEvent.id.desc())
            ):
                events.setdefault(event.task_id, []).append(event)
            for checkpoint in self.session.scalars(
                select(Checkpoint)
                .where(Checkpoint.task_id.in_(chunk))
                .order_by(Checkpoint.created_at.desc(), Checkpoint.id.desc())
            ):
                notes.setdefault(checkpoint.task_id, []).append(checkpoint)
        out = {}
        for task in tasks:
            question = task.status == QUESTION_STATUS
            after = last_any.get(task.id) if question else last_work.get(task.id)
            picked_notes = [
                note_from(c)
                for c in notes.get(task.id, [])
                if c.project_id == task.project_id and (after is None or c.created_at > after)
            ][:NOTES_LIMIT]
            out[task.id] = draft_from(
                task,
                picked_notes,
                entered_from(task, events.get(task.id, [])),
                last_round.get(task.id, 0) + 1,
            )
        return out

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
        # A blocked task waits for the person only while an agent's question waits for an
        # answer. Blocked alone (on a supplier, a date, another task) is not for Review.
        tasks = [
            t
            for t in tasks
            if t.status == WAITING_STATUS
            or (pending.get(t.id) is not None and pending[t.id].kind == "question")
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
        drafts = self._drafts([t for t in tasks if t.id not in pending])
        items = []
        for task in tasks:
            review = pending.get(task.id) or drafts[task.id]
            items.append(
                ReviewItem(
                    kind="task",
                    key=f"task:{task.id}",
                    **self._project_fields(projects[task.project_id]),
                    ref=task.human_id,
                    title=task.title,
                    summary=one_line(review.summary),
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

    def _reviewed_tasks(
        self,
        project_id: str | None,
        projects: dict[str, Project],
        limit: int,
        waiting: Iterable[str] = (),
    ):
        """One line per task: your latest decision on it. A task waiting for you again is in the
        waiting list instead, so it is never listed twice."""
        statement = (
            select(TaskReview, Task)
            .join(Task, Task.id == TaskReview.task_id)
            .where(TaskReview.status.in_(("accepted", "rejected", "answered")))
        )
        if project_id:
            statement = statement.where(TaskReview.project_id == project_id)
        rows = []
        seen: set[str] = set(waiting)
        for review, task in self.session.execute(
            statement.order_by(TaskReview.reviewed_at.desc(), TaskReview.round.desc())
        ):
            if task.id in seen:
                continue
            seen.add(task.id)
            rows.append((review, task))
            if len(rows) >= limit:
                break
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
                summary=one_line(review.summary),
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
            title=one_line(_summary(proposal), 200),
            summary=one_line(proposal.reason or "; ".join(read.changes)),
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

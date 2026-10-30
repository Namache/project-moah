"""Task management: tasks, acceptance criteria, relationships, tags, and current focus.

Every lookup is scoped by ``project_id``. A task id or human ID that exists in another
project is reported as "not found" so one project can never read or link another's data.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import case, func, or_, select
from sqlalchemy import delete as sa_delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.task import (
    AcceptanceCriterion,
    Milestone,
    Tag,
    Task,
    TaskRelationship,
    TaskTag,
)
from app.schemas.task import (
    CriterionCreate,
    CriterionRead,
    CriterionUpdate,
    ProjectOverview,
    RelationshipCreate,
    RelationshipRead,
    TaskCreate,
    TaskDetail,
    TaskMove,
    TaskRef,
    TaskSummary,
    TaskUpdate,
    WorkspaceTask,
)
from app.services.activity import ActivityService
from app.services.errors import conflict, invalid, not_found
from app.services.images import ImageService
from app.services.milestones import MilestoneService
from app.services.projects import ProjectService
from app.services.text import ensure_tags

HUMAN_ID_PATTERN = re.compile(r"([A-Za-z][A-Za-z0-9]{0,9})-(\d{1,6})")
CLOSED_STATUSES = ("completed", "archived")
# Stored type -> (label from the source's view, label from the target's view).
RELATIONSHIP_VIEWS = {
    "parent": ("parent", "child"),
    "depends_on": ("depends_on", "blocks"),
    "related_to": ("related_to", "related_to"),
    "supersedes": ("supersedes", "superseded_by"),
}
# Requested label -> (stored type, whether the endpoints are swapped).
RELATIONSHIP_REQUESTS = {
    "parent": ("parent", False),
    "child": ("parent", True),
    "depends_on": ("depends_on", False),
    "blocks": ("depends_on", True),
    "related_to": ("related_to", False),
    "supersedes": ("supersedes", False),
    "superseded_by": ("supersedes", True),
}


def default_prefix(project: Project) -> str:
    if project.task_prefix:
        return project.task_prefix
    ascii_name = unicodedata.normalize("NFKD", project.name).encode("ascii", "ignore").decode()
    letters = re.sub(r"[^A-Za-z0-9]", "", ascii_name).upper()
    if not letters or not letters[0].isalpha():
        letters = "T" + letters
    return letters[:4]


class TaskService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.projects = ProjectService(session)
        self.milestones = MilestoneService(session)

    # ---- lookup -----------------------------------------------------------------------

    def get(self, project_id: str, task_ref: str) -> Task:
        """Find a task in this project by internal id or human ID (case-insensitive)."""
        statement = select(Task).where(Task.project_id == project_id)
        if HUMAN_ID_PATTERN.fullmatch(task_ref):
            statement = statement.where(func.upper(Task.human_id) == task_ref.upper())
        else:
            statement = statement.where(Task.id == task_ref)
        task = self.session.scalar(statement)
        if task is None:
            self.projects.get(project_id)
            raise not_found(f"Task {task_ref} was not found in this project")
        return task

    # ---- read models ------------------------------------------------------------------

    def list(
        self,
        project_id: str,
        *,
        statuses: Iterable[str] | None = None,
        milestone_id: str | None = None,
        include_archived: bool = False,
    ) -> list[TaskSummary]:
        project = self.projects.get(project_id)
        statement = select(Task).where(Task.project_id == project_id)
        statuses = list(statuses or [])
        if statuses:
            statement = statement.where(Task.status.in_(statuses))
        elif not include_archived:
            statement = statement.where(Task.status != "archived")
        if milestone_id:
            statement = statement.where(Task.milestone_id == milestone_id)
        tasks = list(
            self.session.scalars(statement.order_by(Task.status, Task.sort_order, Task.created_at))
        )
        return self._summaries(tasks, {project_id: project.current_focus_task_id})

    def list_workspace(
        self,
        *,
        statuses: Iterable[str] | None = None,
        project_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[WorkspaceTask]:
        """All Tasks view. Archived projects and archived tasks are excluded by default."""
        statement = (
            select(Task, Project)
            .join(Project, Project.id == Task.project_id)
            .where(Project.status != "archived")
        )
        statuses = list(statuses or [])
        statement = statement.where(
            Task.status.in_(statuses) if statuses else Task.status != "archived"
        )
        if project_id:
            statement = statement.where(Task.project_id == project_id)
        priority_rank = case({"critical": 0, "high": 1, "normal": 2, "low": 3}, value=Task.priority)
        rows = self.session.execute(
            statement.order_by(Project.name_key, priority_rank, Task.sort_order, Task.created_at)
            .limit(limit)
            .offset(offset)
        ).all()
        projects = {project.id: project for _, project in rows}
        summaries = self._summaries(
            [task for task, _ in rows],
            {pid: project.current_focus_task_id for pid, project in projects.items()},
        )
        return [
            WorkspaceTask(
                **summary.model_dump(),
                project_name=projects[summary.project_id].name,
                project_icon=projects[summary.project_id].icon,
                project_accent=projects[summary.project_id].accent,
            )
            for summary in summaries
        ]

    def detail(self, project_id: str, task_ref: str) -> TaskDetail:
        task = self.get(project_id, task_ref)
        self.session.refresh(task, ["criteria"])
        project = self.projects.get(project_id)
        summary = self._summaries([task], {project_id: project.current_focus_task_id})[0]
        milestone = (
            self.milestones.read(project_id, task.milestone_id) if task.milestone_id else None
        )
        return TaskDetail(
            **summary.model_dump(),
            description=task.description,
            acceptance_criteria=[CriterionRead.model_validate(c) for c in task.criteria],
            relationships=self._relationships_for(task),
            milestone=milestone,
            images=ImageService(self.session).for_records("task", [task.id])[task.id],
        )

    def overviews(self, project_ids: list[str]) -> list[ProjectOverview]:
        """Board counts, focus task, and active milestone for many projects at once."""
        if not project_ids:
            return []
        projects = {
            p.id: p
            for p in self.session.scalars(select(Project).where(Project.id.in_(project_ids)))
        }
        counts: dict[str, dict[str, int]] = defaultdict(dict)
        for pid, status, count in self.session.execute(
            select(Task.project_id, Task.status, func.count(Task.id))
            .where(Task.project_id.in_(project_ids))
            .group_by(Task.project_id, Task.status)
        ):
            counts[pid][status] = count

        focus_ids = [p.current_focus_task_id for p in projects.values() if p.current_focus_task_id]
        focus_tasks = list(self.session.scalars(select(Task).where(Task.id.in_(focus_ids))))
        focus = {
            s.project_id: s
            for s in self._summaries(
                focus_tasks, {pid: p.current_focus_task_id for pid, p in projects.items()}
            )
        }

        # Active milestone: the first "active" one by order, else the first "planned".
        milestone_rows = list(
            self.session.scalars(
                select(Milestone)
                .where(
                    Milestone.project_id.in_(project_ids),
                    Milestone.status.in_(("active", "planned")),
                )
                .order_by(
                    Milestone.project_id,
                    case((Milestone.status == "active", 0), else_=1),
                    Milestone.sort_order,
                )
            )
        )
        chosen: dict[str, Milestone] = {}
        for milestone in milestone_rows:
            chosen.setdefault(milestone.project_id, milestone)
        with_progress = {
            m.project_id: m for m in self.milestones.with_progress(list(chosen.values()))
        }

        return [
            ProjectOverview(
                project_id=pid,
                task_counts=counts.get(pid, {}),
                focus_task=focus.get(pid),
                active_milestone=with_progress.get(pid),
            )
            for pid in project_ids
            if pid in projects
        ]

    # ---- task writes ------------------------------------------------------------------

    def create(self, project_id: str, payload: TaskCreate) -> TaskDetail:
        project = self.projects.get(project_id)
        if payload.milestone_id:
            self.milestones.get(project_id, payload.milestone_id)
        prefix = payload.prefix or default_prefix(project)
        number = self._next_number(project_id, prefix)
        now = datetime.now(UTC)
        task = Task(
            project_id=project_id,
            milestone_id=payload.milestone_id,
            prefix=prefix,
            number=number,
            human_id=f"{prefix}-{number:03d}",
            title=payload.title,
            description=payload.description,
            status=payload.status,
            priority=payload.priority,
            next_action=payload.next_action,
            sort_order=self._end_of_column(project_id, payload.status),
            created_at=now,
            updated_at=now,
        )
        self._apply_status_timestamps(task, None, payload.status, now)
        task.criteria = [
            AcceptanceCriterion(description=text, sort_order=index, created_at=now, updated_at=now)
            for index, text in enumerate(payload.acceptance_criteria)
        ]
        self.session.add(task)
        self.session.flush()
        self._set_tags(task, payload.tags)
        self._log_task(task, "TASK_CREATED", {"status": task.status})
        self._commit("A task with this ID already exists in this project")
        return self.detail(project_id, task.id)

    def update(self, project_id: str, task_ref: str, payload: TaskUpdate) -> TaskDetail:
        task = self.get(project_id, task_ref)
        changes = payload.model_dump(exclude_unset=True)
        changed_fields = sorted(changes)
        previous_status = task.status
        now = datetime.now(UTC)
        if "milestone_id" in changes and changes["milestone_id"] is not None:
            self.milestones.get(project_id, changes["milestone_id"])
        if "tags" in changes:
            self._set_tags(task, changes.pop("tags"))
        new_status = changes.pop("status", None)
        for field, value in changes.items():
            setattr(task, field, value)
        if new_status is not None and new_status != task.status:
            self._change_status(task, new_status, now)
            task.sort_order = self._end_of_column(project_id, new_status, exclude=task.id)
        task.updated_at = now
        event_type = (
            self._status_event(previous_status, task.status)
            if previous_status != task.status
            else "TASK_UPDATED"
        )
        self._log_task(
            task,
            event_type,
            {
                "changed_fields": changed_fields,
                "previous_status": previous_status,
                "status": task.status,
            },
        )
        self._commit("The task could not be saved")
        return self.detail(project_id, task.id)

    def move(self, project_id: str, task_ref: str, payload: TaskMove) -> TaskDetail:
        """Place a task at a position in a board column and renumber that column."""
        task = self.get(project_id, task_ref)
        previous_status = task.status
        now = datetime.now(UTC)
        if payload.status != task.status:
            self._change_status(task, payload.status, now)
        column = list(
            self.session.scalars(
                select(Task)
                .where(
                    Task.project_id == project_id,
                    Task.status == payload.status,
                    Task.id != task.id,
                )
                .order_by(Task.sort_order, Task.created_at)
            )
        )
        column.insert(min(payload.index, len(column)), task)
        for position, item in enumerate(column):
            item.sort_order = position
        task.updated_at = now
        self._log_task(
            task,
            self._status_event(previous_status, task.status)
            if previous_status != task.status
            else "TASK_MOVED",
            {"previous_status": previous_status, "status": task.status, "index": payload.index},
        )
        self.session.commit()
        return self.detail(project_id, task.id)

    def delete(self, project_id: str, task_ref: str, metadata: dict | None = None) -> None:
        """Permanently remove a task. The UI offers archive first; this is for mistakes and
        for the Done clean-up. The activity log keeps its entries, titled, without the task."""
        from app.models.graph import DataLink, NodeUsefulness, ShelfMember

        task = self.get(project_id, task_ref)
        project = self.projects.get(project_id)
        if project.current_focus_task_id == task.id:
            project.current_focus_task_id = None
            self.session.flush()
        self._log_task(task, "TASK_DELETED", metadata)
        # Graph rows name the task by kind and id, without a foreign key: drop them with it,
        # so no link, shelf or usefulness score points at a task that is gone.
        self.session.execute(
            sa_delete(DataLink).where(
                or_(
                    (DataLink.source_kind == "task") & (DataLink.source_id == task.id),
                    (DataLink.target_kind == "task") & (DataLink.target_id == task.id),
                )
            )
        )
        for model in (ShelfMember, NodeUsefulness):
            self.session.execute(
                sa_delete(model).where(model.node_kind == "task", model.node_id == task.id)
            )
        self.session.delete(task)
        self.session.commit()

    # ---- focus ------------------------------------------------------------------------

    def set_focus(self, project_id: str, task_ref: str | None) -> Project:
        project = self.projects.get(project_id)
        previous_id = project.current_focus_task_id
        if task_ref is None:
            project.current_focus_task_id = None
        else:
            task = self.get(project_id, task_ref)
            if task.status in CLOSED_STATUSES:
                raise invalid("A completed or archived task cannot be the current focus")
            project.current_focus_task_id = task.id
        project.updated_at = datetime.now(UTC)
        if previous_id != project.current_focus_task_id:
            if project.current_focus_task_id:
                self._log_task(task, "TASK_FOCUS_SET")
            else:
                ActivityService(self.session).record(
                    project_id,
                    "TASK_FOCUS_CLEARED",
                    entity_type="project",
                    entity_id=project_id,
                    metadata={"previous_task_id": previous_id},
                )
        self.session.commit()
        return project

    def start_work(self, project_id: str, task_ref: str) -> TaskDetail:
        """Move the task to In Progress and make it the project's current focus."""
        task = self.get(project_id, task_ref)
        previous_status = task.status
        now = datetime.now(UTC)
        if task.status != "in_progress":
            self._change_status(task, "in_progress", now)
            task.sort_order = self._end_of_column(project_id, "in_progress", exclude=task.id)
        task.updated_at = now
        project = self.projects.get(project_id)
        project.current_focus_task_id = task.id
        project.updated_at = now
        self._log_task(
            task, "TASK_STARTED", {"previous_status": previous_status, "status": task.status}
        )
        self.session.commit()
        return self.detail(project_id, task.id)

    # ---- acceptance criteria ----------------------------------------------------------

    def add_criterion(self, project_id: str, task_ref: str, payload: CriterionCreate) -> TaskDetail:
        task = self.get(project_id, task_ref)
        last = self.session.scalar(
            select(func.max(AcceptanceCriterion.sort_order)).where(
                AcceptanceCriterion.task_id == task.id
            )
        )
        now = datetime.now(UTC)
        self.session.add(
            AcceptanceCriterion(
                task_id=task.id,
                description=payload.description,
                is_completed=payload.is_completed,
                sort_order=0 if last is None else last + 1,
                created_at=now,
                updated_at=now,
            )
        )
        task.updated_at = now
        self._log_task(task, "TASK_CRITERION_ADDED", {"description": payload.description})
        self.session.commit()
        return self.detail(project_id, task.id)

    def update_criterion(
        self, project_id: str, task_ref: str, criterion_id: str, payload: CriterionUpdate
    ) -> TaskDetail:
        task = self.get(project_id, task_ref)
        criterion = self._criterion(task, criterion_id)
        changes = payload.model_dump(exclude_unset=True)
        new_index = changes.pop("sort_order", None)
        for field, value in changes.items():
            setattr(criterion, field, value)
        now = datetime.now(UTC)
        criterion.updated_at = now
        if new_index is not None:
            ordered = [c for c in self._criteria(task.id) if c.id != criterion.id]
            ordered.insert(min(new_index, len(ordered)), criterion)
            for position, item in enumerate(ordered):
                item.sort_order = position
        task.updated_at = now
        self._log_task(
            task,
            "TASK_CRITERION_UPDATED",
            {
                "description": criterion.description,
                "changed_fields": sorted(payload.model_fields_set),
            },
        )
        self.session.commit()
        return self.detail(project_id, task.id)

    def delete_criterion(self, project_id: str, task_ref: str, criterion_id: str) -> TaskDetail:
        task = self.get(project_id, task_ref)
        criterion = self._criterion(task, criterion_id)
        self._log_task(task, "TASK_CRITERION_REMOVED", {"description": criterion.description})
        self.session.delete(criterion)
        self.session.flush()
        for position, item in enumerate(self._criteria(task.id)):
            item.sort_order = position
        task.updated_at = datetime.now(UTC)
        self.session.commit()
        return self.detail(project_id, task.id)

    # ---- relationships ----------------------------------------------------------------

    def add_relationship(
        self, project_id: str, task_ref: str, payload: RelationshipCreate
    ) -> TaskDetail:
        task = self.get(project_id, task_ref)
        other = self.get(project_id, payload.target)
        if other.id == task.id:
            raise invalid("A task cannot be related to itself")
        stored_type, swapped = RELATIONSHIP_REQUESTS[payload.type]
        source, target = (other, task) if swapped else (task, other)
        if stored_type == "related_to" and source.id > target.id:
            source, target = target, source  # one canonical row per unordered pair
        if self._edge_exists(source.id, target.id, stored_type):
            raise conflict("These tasks already have this relationship")
        if stored_type == "parent":
            if self.session.scalar(
                select(TaskRelationship.id).where(
                    TaskRelationship.type == "parent", TaskRelationship.target_task_id == target.id
                )
            ):
                raise conflict(f"{target.human_id} already has a parent task")
        if stored_type in ("parent", "depends_on", "supersedes") and self._reaches(
            project_id, stored_type, start=target.id, goal=source.id
        ):
            raise invalid("This relationship would create a loop between tasks")
        self.session.add(
            TaskRelationship(
                project_id=project_id,
                source_task_id=source.id,
                target_task_id=target.id,
                type=stored_type,
                created_at=datetime.now(UTC),
            )
        )
        self._log_task(
            task,
            "TASK_RELATIONSHIP_ADDED",
            {"type": payload.type, "target_human_id": other.human_id},
        )
        self._commit("These tasks already have this relationship")
        return self.detail(project_id, task.id)

    def remove_relationship(
        self, project_id: str, task_ref: str, relationship_id: str
    ) -> TaskDetail:
        task = self.get(project_id, task_ref)
        edge = self.session.scalar(
            select(TaskRelationship).where(
                TaskRelationship.id == relationship_id,
                TaskRelationship.project_id == project_id,
                or_(
                    TaskRelationship.source_task_id == task.id,
                    TaskRelationship.target_task_id == task.id,
                ),
            )
        )
        if edge is None:
            raise not_found("Relationship not found on this task")
        other_id = edge.target_task_id if edge.source_task_id == task.id else edge.source_task_id
        other = self.get(project_id, other_id)
        self._log_task(
            task,
            "TASK_RELATIONSHIP_REMOVED",
            {"type": edge.type, "target_human_id": other.human_id},
        )
        self.session.delete(edge)
        self.session.commit()
        return self.detail(project_id, task.id)

    # ---- internals --------------------------------------------------------------------

    @staticmethod
    def _status_event(previous: str, current: str) -> str:
        if current == "in_progress":
            return "TASK_STARTED"
        if current == "blocked":
            return "TASK_BLOCKED"
        if current == "completed":
            return "TASK_COMPLETED"
        if current == "archived":
            return "TASK_ARCHIVED"
        if previous in CLOSED_STATUSES:
            return "TASK_REOPENED"
        return "TASK_MOVED"

    def _log_task(self, task: Task, event_type: str, metadata: dict | None = None) -> None:
        ActivityService(self.session).record(
            task.project_id,
            event_type,
            entity_type="task",
            entity_id=task.id,
            task_id=task.id,
            metadata={"title": task.title, "human_id": task.human_id, **(metadata or {})},
        )

    def _summaries(
        self, tasks: list[Task], focus_by_project: dict[str, str | None]
    ) -> list[TaskSummary]:
        if not tasks:
            return []
        ids = [t.id for t in tasks]
        criteria = {
            task_id: (total, done or 0)
            for task_id, total, done in self.session.execute(
                select(
                    AcceptanceCriterion.task_id,
                    func.count(AcceptanceCriterion.id),
                    func.sum(case((AcceptanceCriterion.is_completed, 1), else_=0)),
                )
                .where(AcceptanceCriterion.task_id.in_(ids))
                .group_by(AcceptanceCriterion.task_id)
            )
        }
        tags: dict[str, list[str]] = defaultdict(list)
        for task_id, name in self.session.execute(
            select(TaskTag.task_id, Tag.name)
            .join(Tag, Tag.id == TaskTag.tag_id)
            .where(TaskTag.task_id.in_(ids))
            .order_by(Tag.name_key)
        ):
            tags[task_id].append(name)
        blocked = set(
            self.session.scalars(
                select(TaskRelationship.source_task_id)
                .join(Task, Task.id == TaskRelationship.target_task_id)
                .where(
                    TaskRelationship.type == "depends_on",
                    TaskRelationship.source_task_id.in_(ids),
                    Task.status.not_in(CLOSED_STATUSES),
                )
            )
        )
        result = []
        for task in tasks:
            summary = TaskSummary.model_validate(task)
            summary.criteria_total, summary.criteria_completed = criteria.get(task.id, (0, 0))
            summary.tags = tags.get(task.id, [])
            summary.is_focus = focus_by_project.get(task.project_id) == task.id
            summary.is_blocked_by_open_dependency = task.id in blocked
            result.append(summary)
        return result

    def _relationships_for(self, task: Task) -> list[RelationshipRead]:
        edges = list(
            self.session.scalars(
                select(TaskRelationship)
                .where(
                    TaskRelationship.project_id == task.project_id,
                    or_(
                        TaskRelationship.source_task_id == task.id,
                        TaskRelationship.target_task_id == task.id,
                    ),
                )
                .order_by(TaskRelationship.created_at)
            )
        )
        other_ids = {
            e.target_task_id if e.source_task_id == task.id else e.source_task_id for e in edges
        }
        others = {
            t.id: t
            for t in self.session.scalars(
                select(Task).where(Task.project_id == task.project_id, Task.id.in_(other_ids))
            )
        }
        result = []
        for edge in edges:
            from_source = edge.source_task_id == task.id
            label = RELATIONSHIP_VIEWS[edge.type][0 if from_source else 1]
            other = others[edge.target_task_id if from_source else edge.source_task_id]
            result.append(
                RelationshipRead(id=edge.id, type=label, task=TaskRef.model_validate(other))
            )
        return result

    def _edge_exists(self, source_id: str, target_id: str, stored_type: str) -> bool:
        return (
            self.session.scalar(
                select(TaskRelationship.id).where(
                    TaskRelationship.source_task_id == source_id,
                    TaskRelationship.target_task_id == target_id,
                    TaskRelationship.type == stored_type,
                )
            )
            is not None
        )

    def _reaches(self, project_id: str, stored_type: str, *, start: str, goal: str) -> bool:
        """True if ``goal`` is reachable from ``start`` along edges of one type."""
        edges: dict[str, list[str]] = defaultdict(list)
        for source, target in self.session.execute(
            select(TaskRelationship.source_task_id, TaskRelationship.target_task_id).where(
                TaskRelationship.project_id == project_id, TaskRelationship.type == stored_type
            )
        ):
            edges[source].append(target)
        seen, stack = set(), [start]
        while stack:
            node = stack.pop()
            if node == goal:
                return True
            if node not in seen:
                seen.add(node)
                stack.extend(edges[node])
        return False

    def _next_number(self, project_id: str, prefix: str) -> int:
        last = self.session.scalar(
            select(func.max(Task.number)).where(
                Task.project_id == project_id, Task.prefix == prefix
            )
        )
        return 1 if last is None else last + 1

    def _end_of_column(self, project_id: str, status: str, exclude: str | None = None) -> int:
        statement = select(func.max(Task.sort_order)).where(
            Task.project_id == project_id, Task.status == status
        )
        if exclude:
            statement = statement.where(Task.id != exclude)
        last = self.session.scalar(statement)
        return 0 if last is None else last + 1

    def _change_status(self, task: Task, status: str, now: datetime) -> None:
        previous = task.status
        task.status = status
        self._apply_status_timestamps(task, previous, status, now)
        if status == "completed" and previous != "completed":
            self._settle_completion_proposals(task, now)
        if status in CLOSED_STATUSES:
            project = self.projects.get(task.project_id)
            if project.current_focus_task_id == task.id:
                project.current_focus_task_id = None

    def _settle_completion_proposals(self, task: Task, now: datetime) -> None:
        """Completing a task directly does what an agent's waiting "complete this task" proposal
        asked, so that proposal is settled as accepted instead of staying in Review for a change
        that can no longer apply. One that also asks to tick every requirement keeps waiting."""
        from app.models.proposal import Proposal

        for proposal in self.session.scalars(
            select(Proposal).where(
                Proposal.project_id == task.project_id,
                Proposal.status == "pending",
                Proposal.proposal_type == "complete_task",
                Proposal.target_entity_id == task.id,
            )
        ):
            if (proposal.payload or {}).get("complete_all_criteria"):
                continue
            proposal.status, proposal.reviewed_at, proposal.error = "accepted", now, None
            proposal.review_note = "The task was completed directly."

    @staticmethod
    def _apply_status_timestamps(
        task: Task, previous: str | None, status: str, now: datetime
    ) -> None:
        if status == "in_progress" and task.started_at is None:
            task.started_at = now
        if status == "completed":
            task.completed_at = task.completed_at if previous == "completed" else now
        elif previous == "completed":
            task.completed_at = None
        if status == "archived":
            task.archived_at = task.archived_at if previous == "archived" else now
        elif previous == "archived":
            task.archived_at = None

    def _set_tags(self, task: Task, names: list[str]) -> None:
        wanted_ids = ensure_tags(self.session, task.project_id, names)
        current = {
            link.tag_id: link
            for link in self.session.scalars(select(TaskTag).where(TaskTag.task_id == task.id))
        }
        for tag_id, link in current.items():
            if tag_id not in wanted_ids:
                self.session.delete(link)
        for tag_id in wanted_ids - current.keys():
            self.session.add(TaskTag(task_id=task.id, tag_id=tag_id, project_id=task.project_id))

    def _criteria(self, task_id: str) -> list[AcceptanceCriterion]:
        return list(
            self.session.scalars(
                select(AcceptanceCriterion)
                .where(AcceptanceCriterion.task_id == task_id)
                .order_by(AcceptanceCriterion.sort_order, AcceptanceCriterion.created_at)
            )
        )

    def _criterion(self, task: Task, criterion_id: str) -> AcceptanceCriterion:
        criterion = self.session.scalar(
            select(AcceptanceCriterion).where(
                AcceptanceCriterion.id == criterion_id, AcceptanceCriterion.task_id == task.id
            )
        )
        if criterion is None:
            raise not_found("Acceptance criterion not found on this task")
        return criterion

    def _commit(self, conflict_message: str) -> None:
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise conflict(conflict_message) from exc

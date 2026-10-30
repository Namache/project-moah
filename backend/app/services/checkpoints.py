"""Project-scoped development checkpoints and latest-checkpoint resolution."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.checkpoint import Checkpoint
from app.models.task import Task
from app.schemas.checkpoint import CheckpointCreate, CheckpointRead, CheckpointUpdate
from app.schemas.task import TaskRef
from app.services.activity import ActivityService
from app.services.errors import not_found
from app.services.projects import ProjectService
from app.services.tasks import TaskService


class CheckpointService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.projects = ProjectService(session)
        self.tasks = TaskService(session)
        self.activity = ActivityService(session)

    def get(self, project_id: str, checkpoint_id: str) -> Checkpoint:
        checkpoint = self.session.scalar(
            select(Checkpoint).where(
                Checkpoint.project_id == project_id, Checkpoint.id == checkpoint_id
            )
        )
        if checkpoint is None:
            self.projects.get(project_id)
            raise not_found("Checkpoint was not found in this project")
        return checkpoint

    def read(self, project_id: str, checkpoint_id: str) -> CheckpointRead:
        return self._reads(project_id, [self.get(project_id, checkpoint_id)])[0]

    def list(
        self,
        project_id: str,
        *,
        task: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CheckpointRead]:
        self.projects.get(project_id)
        statement = select(Checkpoint).where(Checkpoint.project_id == project_id)
        if task is not None:
            statement = statement.where(Checkpoint.task_id == self.tasks.get(project_id, task).id)
        checkpoints = list(
            self.session.scalars(
                statement.order_by(Checkpoint.created_at.desc(), Checkpoint.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        return self._reads(project_id, checkpoints)

    def latest(self, project_id: str, *, task: str | None = None) -> CheckpointRead:
        found = self.list(project_id, task=task, limit=1)
        if not found:
            raise not_found(
                "No checkpoint was found"
                if task is None
                else "No checkpoint was found for this task"
            )
        return found[0]

    def create(
        self,
        project_id: str,
        payload: CheckpointCreate,
        *,
        actor_type: str = "human",
        actor_name: str | None = None,
    ) -> CheckpointRead:
        self.projects.get(project_id)
        task = self.tasks.get(project_id, payload.task_id) if payload.task_id else None
        now = datetime.now(UTC)
        checkpoint = Checkpoint(
            project_id=project_id,
            task_id=task.id if task else None,
            task_project_id=project_id if task else None,
            title=payload.title,
            summary=payload.summary,
            completed_work=payload.completed_work,
            remaining_work=payload.remaining_work,
            problems=payload.problems,
            next_steps=payload.next_steps,
            agent=payload.agent,
            git_commit=payload.git_commit,
            created_at=now,
            updated_at=now,
        )
        self.session.add(checkpoint)
        self.session.flush()
        self.activity.record(
            project_id,
            "CHECKPOINT_CREATED",
            actor_type=actor_type,
            actor_name=actor_name,
            entity_type="checkpoint",
            entity_id=checkpoint.id,
            task_id=checkpoint.task_id,
            metadata={
                "title": checkpoint.title,
                "task_human_id": task.human_id if task else None,
                "agent": checkpoint.agent,
            },
        )
        self.session.commit()
        if checkpoint.task_id is not None:
            # Mild evidence that the task's latest context pack was put to use.
            from app.services.retrieval import RetrievalService

            try:
                RetrievalService(self.session).on_checkpoint(
                    project_id, checkpoint.task_id, actor_name or actor_type
                )
            except Exception:  # noqa: BLE001 - learning never blocks a checkpoint
                self.session.rollback()
        return self.read(project_id, checkpoint.id)

    def update(
        self,
        project_id: str,
        checkpoint_id: str,
        payload: CheckpointUpdate,
        *,
        actor_type: str = "human",
        actor_name: str | None = None,
    ) -> CheckpointRead:
        checkpoint = self.get(project_id, checkpoint_id)
        changes = payload.model_dump(exclude_unset=True)
        if "task_id" in changes:
            task = self.tasks.get(project_id, changes["task_id"]) if changes["task_id"] else None
            checkpoint.task_id = task.id if task else None
            checkpoint.task_project_id = project_id if task else None
            changes.pop("task_id")
        for field, value in changes.items():
            setattr(checkpoint, field, value)
        checkpoint.updated_at = datetime.now(UTC)
        self.activity.record(
            project_id,
            "CHECKPOINT_UPDATED",
            actor_type=actor_type,
            actor_name=actor_name,
            entity_type="checkpoint",
            entity_id=checkpoint.id,
            task_id=checkpoint.task_id,
            metadata={
                "title": checkpoint.title,
                "changed_fields": sorted(payload.model_fields_set),
            },
        )
        self.session.commit()
        return self.read(project_id, checkpoint.id)

    def _reads(self, project_id: str, checkpoints: list[Checkpoint]) -> list[CheckpointRead]:
        task_ids = {checkpoint.task_id for checkpoint in checkpoints if checkpoint.task_id}
        tasks = {
            task.id: TaskRef.model_validate(task)
            for task in self.session.scalars(
                select(Task).where(Task.project_id == project_id, Task.id.in_(task_ids))
            )
        }
        return [
            CheckpointRead.model_validate(checkpoint).model_copy(
                update={"task": tasks.get(checkpoint.task_id)}
            )
            for checkpoint in checkpoints
        ]

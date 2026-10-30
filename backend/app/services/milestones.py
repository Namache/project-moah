from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.task import Milestone, Task
from app.schemas.task import MilestoneCreate, MilestoneRead, MilestoneUpdate
from app.services.activity import ActivityService
from app.services.errors import not_found
from app.services.projects import ProjectService


class MilestoneService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.projects = ProjectService(session)

    def list(self, project_id: str, *, include_archived: bool = False) -> list[MilestoneRead]:
        self.projects.get(project_id)
        statement = select(Milestone).where(Milestone.project_id == project_id)
        if not include_archived:
            statement = statement.where(Milestone.status != "archived")
        milestones = list(
            self.session.scalars(statement.order_by(Milestone.sort_order, Milestone.created_at))
        )
        return self.with_progress(milestones)

    def get(self, project_id: str, milestone_id: str) -> Milestone:
        milestone = self.session.scalar(
            select(Milestone).where(
                Milestone.id == milestone_id, Milestone.project_id == project_id
            )
        )
        if milestone is None:
            raise not_found("Milestone not found in this project")
        return milestone

    def read(self, project_id: str, milestone_id: str) -> MilestoneRead:
        return self.with_progress([self.get(project_id, milestone_id)])[0]

    def create(self, project_id: str, payload: MilestoneCreate) -> MilestoneRead:
        self.projects.get(project_id)
        last = self.session.scalar(
            select(func.max(Milestone.sort_order)).where(Milestone.project_id == project_id)
        )
        now = datetime.now(UTC)
        milestone = Milestone(
            project_id=project_id,
            name=payload.name,
            description=payload.description,
            status=payload.status,
            target_date=payload.target_date,
            sort_order=0 if last is None else last + 1,
            created_at=now,
            updated_at=now,
        )
        self.session.add(milestone)
        self.session.flush()
        ActivityService(self.session).record(
            project_id,
            "MILESTONE_CREATED",
            entity_type="milestone",
            entity_id=milestone.id,
            metadata={"name": milestone.name},
        )
        self.session.commit()
        return self.read(project_id, milestone.id)

    def update(self, project_id: str, milestone_id: str, payload: MilestoneUpdate) -> MilestoneRead:
        milestone = self.get(project_id, milestone_id)
        changes = payload.model_dump(exclude_unset=True)
        previous_status = milestone.status
        requested_order = changes.pop("sort_order", None)
        for field, value in changes.items():
            setattr(milestone, field, value)
        if requested_order is not None:
            ordered = list(
                self.session.scalars(
                    select(Milestone)
                    .where(Milestone.project_id == project_id)
                    .order_by(Milestone.sort_order, Milestone.created_at)
                )
            )
            ordered.remove(milestone)
            ordered.insert(min(requested_order, len(ordered)), milestone)
            for index, item in enumerate(ordered):
                item.sort_order = index
        milestone.updated_at = datetime.now(UTC)
        ActivityService(self.session).record(
            project_id,
            "MILESTONE_ARCHIVED"
            if milestone.status == "archived" and previous_status != "archived"
            else "MILESTONE_UPDATED",
            entity_type="milestone",
            entity_id=milestone.id,
            metadata={"name": milestone.name, "changed_fields": sorted(payload.model_fields_set)},
        )
        self.session.commit()
        return self.read(project_id, milestone_id)

    def with_progress(self, milestones: list[Milestone]) -> list[MilestoneRead]:
        """Attach live task counts in one grouped query; archived tasks are not counted."""
        if not milestones:
            return []
        rows = self.session.execute(
            select(
                Task.milestone_id,
                func.count(Task.id),
                func.sum(case((Task.status == "completed", 1), else_=0)),
            )
            .where(
                Task.milestone_id.in_([m.id for m in milestones]),
                Task.status != "archived",
            )
            .group_by(Task.milestone_id)
        ).all()
        counts = {milestone_id: (total, done or 0) for milestone_id, total, done in rows}
        result = []
        for milestone in milestones:
            total, done = counts.get(milestone.id, (0, 0))
            read = MilestoneRead.model_validate(milestone)
            read.task_count, read.completed_task_count = total, done
            result.append(read)
        return result

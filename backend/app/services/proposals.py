"""AI proposals: an agent suggests a change, a person reviews it, and only then it applies.

Agents record proposals through the MCP adapter. Nothing in a proposal changes project truth
until a person accepts it. Accepting is a human decision, so it may change locked memory:
the reviewer sees exactly what will change, which is the point of the lock. A failed accept
changes nothing and leaves the proposal pending with the reason recorded.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.proposal import Proposal
from app.models.task import AcceptanceCriterion
from app.schemas.files import FileCreate, FileUpdate
from app.schemas.memory import MemoryCreate, MemorySupersede, MemoryUpdate
from app.schemas.proposal import (
    AcceptAllResult,
    PendingCount,
    PendingProposal,
    ProposalAccept,
    ProposalCreate,
    ProposalRead,
)
from app.schemas.task import CriterionCreate, TaskUpdate
from app.services.activity import ActivityService
from app.services.errors import conflict, invalid, not_found
from app.services.files import FileService
from app.services.memory import MemoryService
from app.services.projects import ProjectService
from app.services.tasks import CLOSED_STATUSES, TaskService

MEMORY_TARGETS = {"update_memory", "supersede_memory"}
NEWEST_PENDING = 10


def _summary(proposal: Proposal) -> str:
    """One line for a notification: the proposed title, else the agent's reason, else the kind."""
    title = proposal.payload.get("title") if isinstance(proposal.payload, dict) else None
    text = " ".join(str(title or proposal.reason or proposal.proposal_type).split())
    return text if len(text) <= 120 else text[:119] + "…"


TASK_TARGETS = {"complete_task", "update_task", "add_acceptance_criterion"}


class CompleteTaskPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Also mark every acceptance criterion done. Off by default: criteria are the evidence.
    complete_all_criteria: bool = False


class AssociateFilePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=1024)
    purpose: str | None = Field(default=None, max_length=2000)
    summary: str | None = Field(default=None, max_length=8000)
    task_ids: list[str] = Field(default_factory=list, max_length=50)
    memory_ids: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("purpose", "summary")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


def actor_for(agent: str) -> str:
    """The activity actor type for an agent name."""
    lowered = agent.lower()
    return lowered if lowered in ("codex", "claude") else "system"


class ProposalService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.projects = ProjectService(session)
        self.tasks = TaskService(session)
        self.memory = MemoryService(session)
        self.files = FileService(session)
        self.activity = ActivityService(session)

    # ---- reads ------------------------------------------------------------------------

    def get(self, project_id: str, ref: str) -> Proposal:
        statement = select(Proposal).where(Proposal.project_id == project_id)
        statement = statement.where(
            func.upper(Proposal.human_id) == ref.upper()
            if ref.upper().startswith("PROP-")
            else Proposal.id == ref
        )
        found = self.session.scalar(statement)
        if found is None:
            self.projects.get(project_id)
            raise not_found(f"Proposal {ref} was not found in this project")
        return found

    def read(self, project_id: str, ref: str) -> ProposalRead:
        return self._read(self.get(project_id, ref))

    def list(
        self,
        project_id: str,
        *,
        statuses: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ProposalRead]:
        self.projects.get(project_id)
        statement = select(Proposal).where(Proposal.project_id == project_id)
        statement = statement.where(Proposal.status.in_(statuses or ["pending"]))
        rows = self.session.scalars(
            statement.order_by(Proposal.created_at.desc(), Proposal.id).limit(limit).offset(offset)
        )
        return [self._read(p) for p in rows]

    def pending_count(self, project_id: str) -> int:
        """How many proposals in one project wait for a person's review."""
        return self.session.scalar(
            select(func.count(Proposal.id)).where(
                Proposal.project_id == project_id, Proposal.status == "pending"
            )
        )

    def pending_counts(self) -> PendingCount:
        rows = self.session.execute(
            select(Proposal.project_id, func.count(Proposal.id))
            .join(Project, Project.id == Proposal.project_id)
            .where(Proposal.status == "pending", Project.status != "archived")
            .group_by(Proposal.project_id)
        ).all()
        by_project = {pid: count for pid, count in rows}
        newest = self.session.execute(
            select(Proposal, Project.name)
            .join(Project, Project.id == Proposal.project_id)
            .where(Proposal.status == "pending", Project.status != "archived")
            .order_by(Proposal.created_at.desc())
            .limit(NEWEST_PENDING)
        ).all()
        return PendingCount(
            total=sum(by_project.values()),
            by_project=by_project,
            newest=[
                PendingProposal(
                    id=proposal.id,
                    project_id=proposal.project_id,
                    project_name=name,
                    human_id=proposal.human_id,
                    agent=proposal.agent,
                    summary=_summary(proposal),
                )
                for proposal, name in newest
            ],
        )

    # ---- create -----------------------------------------------------------------------

    def create(
        self, project_id: str, payload: ProposalCreate, agent: str | None = None
    ) -> ProposalRead:
        self.projects.get(project_id)
        name = (agent or payload.agent or "agent").strip() or "agent"
        entity_type, entity_id, clean = self._validate(
            project_id, payload.proposal_type, payload.target, payload.payload
        )
        record = Proposal(
            project_id=project_id,
            human_id=self._next_human_id(project_id),
            agent=name,
            proposal_type=payload.proposal_type,
            target_entity_type=entity_type,
            target_entity_id=entity_id,
            payload=clean,
            snapshot=self._snapshot(project_id, payload.proposal_type, entity_id, clean),
            reason=payload.reason.strip(),
            status="pending",
            created_at=datetime.now(UTC),
        )
        self.session.add(record)
        self.session.flush()
        self.activity.record(
            project_id,
            "PROPOSAL_CREATED",
            actor_type=actor_for(name),
            actor_name=name,
            entity_type="proposal",
            entity_id=record.id,
            metadata={"title": f"{record.human_id} {record.proposal_type.replace('_', ' ')}"},
        )
        self._commit()
        return self._read(record)

    # ---- review -----------------------------------------------------------------------

    def accept(
        self, project_id: str, ref: str, review: ProposalAccept | None = None
    ) -> ProposalRead:
        review = review or ProposalAccept()
        record = self.get(project_id, ref)
        if record.status != "pending":
            raise conflict(f"{record.human_id} was already {record.status}")
        raw = review.payload if review.payload is not None else record.payload
        try:
            entity_type, entity_id, clean = self._validate(
                project_id, record.proposal_type, record.target_entity_id, raw, accepting=True
            )
            now = datetime.now(UTC)
            record.status, record.reviewed_at, record.review_note = "accepted", now, review.note
            record.applied_payload = clean if review.payload is not None else None
            record.error = None
            self.activity.record(
                project_id,
                "PROPOSAL_ACCEPTED",
                actor_type="human",
                entity_type="proposal",
                entity_id=record.id,
                metadata={
                    "title": f"{record.human_id} {record.proposal_type.replace('_', ' ')}",
                    "edited": review.payload is not None,
                    "agent": record.agent,
                },
            )
            changed = self._apply(
                project_id, record.proposal_type, entity_id, clean
            )  # its commit saves all of this
        except Exception as exc:
            self.session.rollback()
            detail = getattr(exc, "detail", None) or str(exc)
            failed = self.session.get(Proposal, record.id)
            if failed is not None:
                failed.error = str(detail)[:1000]
                self.session.commit()
            raise
        if changed:
            # New or changed knowledge gets linked, as when a person writes it directly.
            from app.services.discovery import discover_quietly

            discover_quietly(self.session, project_id, changed)
        return self._read(self.get(project_id, record.id))

    def reject(self, project_id: str, ref: str, note: str | None = None) -> ProposalRead:
        record = self.get(project_id, ref)
        if record.status != "pending":
            raise conflict(f"{record.human_id} was already {record.status}")
        record.status, record.reviewed_at, record.review_note = "rejected", datetime.now(UTC), note
        self.activity.record(
            project_id,
            "PROPOSAL_REJECTED",
            actor_type="human",
            entity_type="proposal",
            entity_id=record.id,
            metadata={
                "title": f"{record.human_id} {record.proposal_type.replace('_', ' ')}",
                "agent": record.agent,
            },
        )
        self.session.commit()
        return self._read(record)

    def accept_all(self, project_id: str) -> AcceptAllResult:
        """Accept every pending proposal, oldest first. One failure never blocks the others."""
        pending = self.session.scalars(
            select(Proposal)
            .where(Proposal.project_id == project_id, Proposal.status == "pending")
            .order_by(Proposal.created_at, Proposal.id)
        ).all()
        accepted: list[ProposalRead] = []
        failed: list[ProposalRead] = []
        for record in list(pending):
            record_id = record.id
            try:
                accepted.append(self.accept(project_id, record_id))
            except Exception:  # noqa: BLE001 - reported per proposal below
                failed.append(self._read(self.get(project_id, record_id)))
        return AcceptAllResult(accepted=accepted, failed=failed)

    # ---- validation and application ---------------------------------------------------

    def _validate(
        self,
        project_id: str,
        kind: str,
        target: str | None,
        raw: dict[str, Any],
        accepting: bool = False,
    ) -> tuple[str | None, str | None, dict[str, Any]]:
        """Check the payload and target for this type. Returns (entity type, entity id, payload)."""
        try:
            return self._validate_inner(project_id, kind, target, dict(raw), accepting)
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first["loc"])
            raise invalid(f"The proposed change is not valid ({where}: {first['msg']})") from exc

    def _validate_inner(
        self,
        project_id: str,
        kind: str,
        target: str | None,
        raw: dict[str, Any],
        accepting: bool = False,
    ):
        if kind in MEMORY_TARGETS | TASK_TARGETS and not target:
            raise invalid(
                f"A {kind.replace('_', ' ')} proposal needs the ID of the record it changes"
            )
        if kind in ("create_memory", "create_bug"):
            if kind == "create_bug":
                raw["type"] = "bug"
            data = MemoryCreate.model_validate(raw)
            self.tasks_exist(project_id, data.task_ids)
            for ref in data.related:  # found now, not when a person accepts it
                self.memory.get(project_id, ref)
            return None, None, data.model_dump(exclude_defaults=False, mode="json")
        if kind in MEMORY_TARGETS:
            memory = self.memory.get(project_id, target)  # 404 inside another project
            if memory.status != "active":
                raise conflict(f"{memory.human_id} is {memory.status} and can no longer be changed")
            model = MemoryUpdate if kind == "update_memory" else MemorySupersede
            data = model.model_validate(raw)
            if kind == "update_memory":
                self.tasks_exist(project_id, data.task_ids or [])
            return "memory", memory.id, data.model_dump(exclude_unset=True, mode="json")
        if kind in TASK_TARGETS:
            task = self.tasks.get(project_id, target)
            # Accepting "complete this task" after someone already completed it asks for nothing
            # new, so it settles the proposal. Anything else on a closed task cannot apply.
            settled = accepting and kind == "complete_task" and task.status == "completed"
            if kind in ("complete_task", "update_task") and task.status in CLOSED_STATUSES:
                if not settled:
                    raise conflict(f"{task.human_id} is already {task.status}")
            if kind == "complete_task":
                data = CompleteTaskPayload.model_validate(raw)
            elif kind == "update_task":
                data = TaskUpdate.model_validate(raw)
                if data.milestone_id:
                    self.tasks.milestones.get(project_id, data.milestone_id)
            else:
                data = CriterionCreate.model_validate(raw)
            return "task", task.id, data.model_dump(exclude_unset=True, mode="json")
        if kind == "associate_file":
            data = AssociateFilePayload.model_validate(raw)
            FileCreate.model_validate(data.model_dump())  # path and fields checked like a new note
            from app.services.git import normalize_repo_path

            data.path = normalize_repo_path(data.path)
            self.tasks_exist(project_id, data.task_ids)
            for ref in data.memory_ids:
                self.memory.get(project_id, ref)
            return "file", None, data.model_dump(mode="json")
        raise invalid("Unknown proposal type")

    def tasks_exist(self, project_id: str, refs: list[str]) -> None:
        for ref in refs:
            self.tasks.get(project_id, ref)

    def _apply(
        self, project_id: str, kind: str, entity_id: str | None, data: dict[str, Any]
    ) -> str | None:
        """Make the change as a person. The final service call commits everything staged.
        Returns the record to run link discovery on, if any."""
        if kind in ("create_memory", "create_bug"):
            created = self.memory.create(project_id, MemoryCreate.model_validate(data))
            return f"memory:{created.id}"
        if kind == "update_memory":
            self.memory.update(project_id, entity_id, MemoryUpdate.model_validate(data))
            return f"memory:{entity_id}"
        elif kind == "supersede_memory":
            new = self.memory.supersede(project_id, entity_id, MemorySupersede.model_validate(data))
            return f"memory:{new.id}"
        elif kind == "update_task":
            self.tasks.update(project_id, entity_id, TaskUpdate.model_validate(data))
            return f"task:{entity_id}"
        elif kind == "add_acceptance_criterion":
            self.tasks.add_criterion(project_id, entity_id, CriterionCreate.model_validate(data))
        elif kind == "complete_task":
            if CompleteTaskPayload.model_validate(data).complete_all_criteria:
                now = datetime.now(UTC)
                for criterion in self.session.scalars(
                    select(AcceptanceCriterion).where(AcceptanceCriterion.task_id == entity_id)
                ):
                    criterion.is_completed, criterion.updated_at = True, now
            if self.tasks.get(project_id, entity_id).status == "completed":
                self.session.commit()  # already done; only the proposal and criteria change
            else:
                self.tasks.update(project_id, entity_id, TaskUpdate(status="completed"))
        elif kind == "associate_file":
            self._apply_file(project_id, AssociateFilePayload.model_validate(data))

    def _apply_file(self, project_id: str, data: AssociateFilePayload) -> None:
        try:
            existing = self.files.get(project_id, data.path)
        except HTTPException as error:
            if error.status_code != 404:
                raise
            # No notes yet, so create them.
            self.files.create(
                project_id,
                FileCreate(
                    path=data.path,
                    purpose=data.purpose,
                    summary=data.summary,
                    task_ids=data.task_ids,
                    memory_ids=data.memory_ids,
                ),
            )
            return
        current = self.files.read(project_id, existing.id)
        changes: dict[str, Any] = {
            "task_ids": sorted(
                {t.id for t in current.tasks}
                | {self.tasks.get(project_id, r).id for r in data.task_ids}
            ),
            "memory_ids": sorted(
                {m.id for m in current.memories}
                | {self.memory.get(project_id, r).id for r in data.memory_ids}
            ),
        }
        if data.purpose:
            changes["purpose"] = data.purpose
        if data.summary:
            changes["summary"] = data.summary
        self.files.update(project_id, existing.id, FileUpdate.model_validate(changes))

    # ---- presentation -----------------------------------------------------------------

    def _snapshot(self, project_id: str, kind: str, entity_id: str | None, data: dict[str, Any]):
        if kind in MEMORY_TARGETS and entity_id:
            m = self.memory.read(project_id, entity_id)
            return {
                "human_id": m.human_id,
                "title": m.title,
                "content": m.content,
                "importance": m.importance,
                "ai_visibility": m.ai_visibility,
                "is_pinned": m.is_pinned,
                "is_locked": m.is_locked,
                "tags": m.tags,
            }
        if kind in TASK_TARGETS and entity_id:
            t = self.tasks.detail(project_id, entity_id)
            return {
                "human_id": t.human_id,
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "next_action": t.next_action,
                "description": t.description,
                "tags": t.tags,
                "criteria_completed": t.criteria_completed,
                "criteria_total": t.criteria_total,
                "milestone_id": t.milestone_id,
            }
        return None

    def _read(self, record: Proposal) -> ProposalRead:
        read = ProposalRead.model_validate(record)
        snap = record.snapshot or {}
        read.target_label = f"{snap['human_id']} {snap['title']}" if snap.get("human_id") else None
        read.target_locked = bool(snap.get("is_locked"))
        shown = record.applied_payload or record.payload
        read.changes = self._describe(record.proposal_type, shown, snap)
        return read

    @staticmethod
    def _describe(kind: str, data: dict[str, Any], snap: dict[str, Any]) -> list[str]:
        def show(value: Any) -> str:
            if isinstance(value, list):
                return ", ".join(map(str, value)) or "none"
            return "none" if value in (None, "") else str(value)

        lines: list[str] = []
        if kind in ("create_memory", "create_bug"):
            lines.append(f"New {data.get('type', 'memory')}: {data.get('title', '')}")
            if data.get("content"):
                lines.append(f"Details: {data['content']}")
        elif kind in ("update_memory", "update_task"):
            for key, new in data.items():
                if key in ("task_ids",):
                    lines.append(f"Linked tasks → {show(new)}")
                else:
                    lines.append(
                        f"{key.replace('_', ' ').capitalize()}: {show(snap.get(key))} → {show(new)}"
                    )
        elif kind == "supersede_memory":
            lines.append(f"Replace “{snap.get('title', '')}” with “{data.get('title', '')}”")
            if data.get("content"):
                lines.append(f"New details: {data['content']}")
        elif kind == "complete_task":
            done, total = snap.get("criteria_completed", 0), snap.get("criteria_total", 0)
            lines.append(f"Status: {show(snap.get('status')).replace('_', ' ')} → completed")
            lines.append(
                f"Requirements: all {total} will be marked done"
                if data.get("complete_all_criteria")
                else f"Requirements: {done} of {total} done now, unchanged by this"
            )
        elif kind == "add_acceptance_criterion":
            lines.append(f"Add requirement: {data.get('description', '')}")
        elif kind == "associate_file":
            lines.append(f"Add notes for {data.get('path', '')}")
            if data.get("purpose"):
                lines.append(f"Purpose: {data['purpose']}")
            for key, label in (("task_ids", "Tasks"), ("memory_ids", "Memory")):
                if data.get(key):
                    lines.append(f"{label}: {show(data[key])}")
        return lines

    def _next_human_id(self, project_id: str) -> str:
        ids = self.session.scalars(
            select(Proposal.human_id).where(Proposal.project_id == project_id)
        )
        return f"PROP-{max((int(i.split('-')[1]) for i in ids), default=0) + 1:03d}"

    def _commit(self) -> None:
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise conflict("The proposal could not be saved") from exc

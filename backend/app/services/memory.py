"""Durable project memory: decisions, rules, facts, ideas, bugs, notes, and warnings.

Rules enforced here, not in the UI:
- Every lookup is scoped by ``project_id``; another project's memory is "not found".
- A locked memory cannot be edited, replaced, invalidated, archived, or deleted by any
  actor other than a human. Humans must unlock it before deleting it.
- Replacing a memory keeps the old record as ``superseded`` and links the new one to it.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.models.files import FileMemory
from app.models.graph import DataLink
from app.models.memory import TYPE_PREFIXES, Memory, MemoryLink, MemoryTag, MemoryTask
from app.models.task import Tag, Task
from app.schemas.memory import (
    HUMAN,
    MemoryCounts,
    MemoryCreate,
    MemoryHistory,
    MemoryRead,
    MemoryRef,
    MemorySupersede,
    MemoryUpdate,
)
from app.schemas.task import TaskRef
from app.services.activity import ActivityService
from app.services.errors import conflict, locked, not_found
from app.services.images import ImageService
from app.services.projects import ProjectService
from app.services.tasks import TaskService
from app.services.text import contains_pattern, ensure_tags, name_key

HUMAN_ID_PATTERN = re.compile(r"[A-Za-z]{2,10}-\d{1,6}")
IMPORTANCE_RANK = {"critical": 0, "high": 1, "normal": 2, "low": 3}
# Fields a locked memory protects. Pinning and linking tasks are still allowed.
PROTECTED_FIELDS = {
    "title",
    "content",
    "importance",
    "ai_visibility",
    "confidence",
    "source_type",
    "source_reference",
    "tags",
    "is_resolved",
    "pending_note",
}


class MemoryService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.projects = ProjectService(session)
        self.tasks = TaskService(session)

    # ---- lookup and reads -------------------------------------------------------------

    def get(self, project_id: str, ref: str) -> Memory:
        statement = select(Memory).where(Memory.project_id == project_id)
        if HUMAN_ID_PATTERN.fullmatch(ref):
            statement = statement.where(func.upper(Memory.human_id) == ref.upper())
        else:
            statement = statement.where(Memory.id == ref)
        memory = self.session.scalar(statement)
        if memory is None:
            self.projects.get(project_id)
            raise not_found(f"Memory {ref} was not found in this project")
        return memory

    def read(self, project_id: str, ref: str) -> MemoryRead:
        return self._reads([self.get(project_id, ref)])[0]

    def list(
        self,
        project_id: str,
        *,
        types: Iterable[str] | None = None,
        statuses: Iterable[str] | None = None,
        visibility: Iterable[str] | None = None,
        pinned: bool | None = None,
        locked_only: bool | None = None,
        resolved: bool | None = None,
        tag: str | None = None,
        task: str | None = None,
        q: str | None = None,
        sort: str = "priority",
        limit: int = 200,
        offset: int = 0,
        ids: Iterable[str] | None = None,
        refs: Iterable[str] | None = None,
    ) -> list[MemoryRead]:
        """``ids`` keeps only those record ids; ``refs`` only records whose ID (DEC-003) or id
        matches, ignoring case."""
        self.projects.get(project_id)
        statement = select(Memory).where(Memory.project_id == project_id)
        if ids is not None:
            statement = statement.where(Memory.id.in_(list(ids)))
        if refs is not None:
            wanted = [r.upper() for r in refs]
            statement = statement.where(
                or_(func.upper(Memory.human_id).in_(wanted), func.upper(Memory.id).in_(wanted))
            )
        statement = statement.where(Memory.status.in_(list(statuses or ["active"])))
        if types:
            statement = statement.where(Memory.type.in_(list(types)))
        if visibility:
            statement = statement.where(Memory.ai_visibility.in_(list(visibility)))
        if pinned is not None:
            statement = statement.where(Memory.is_pinned == pinned)
        if locked_only is not None:
            statement = statement.where(Memory.is_locked == locked_only)
        if resolved is not None:
            statement = statement.where(Memory.is_resolved == resolved)
        if tag:
            statement = statement.where(
                Memory.id.in_(
                    select(MemoryTag.memory_id)
                    .join(Tag, Tag.id == MemoryTag.tag_id)
                    .where(Tag.project_id == project_id, Tag.name_key == name_key(tag))
                )
            )
        if task:
            linked = self.tasks.get(project_id, task)
            statement = statement.where(
                Memory.id.in_(select(MemoryTask.memory_id).where(MemoryTask.task_id == linked.id))
            )
        if q and q.strip():
            like = contains_pattern(q)
            statement = statement.where(
                or_(
                    func.casefold(Memory.title).like(like, escape="\\"),
                    func.casefold(Memory.content).like(like, escape="\\"),
                    func.casefold(Memory.human_id).like(like, escape="\\"),
                )
            )
        rank = case(IMPORTANCE_RANK, value=Memory.importance)
        ordering = {
            "priority": (Memory.is_pinned.desc(), rank, Memory.updated_at.desc(), Memory.id),
            "updated_desc": (Memory.updated_at.desc(), Memory.id),
            "updated_asc": (Memory.updated_at.asc(), Memory.id),
            "title_asc": (func.casefold(Memory.title), Memory.id),
        }[sort]
        rows = self.session.scalars(statement.order_by(*ordering).limit(limit).offset(offset))
        return self._reads(list(rows))

    def counts(self, project_id: str) -> MemoryCounts:
        self.projects.get(project_id)
        by_type = {
            memory_type: count
            for memory_type, count in self.session.execute(
                select(Memory.type, func.count(Memory.id))
                .where(Memory.project_id == project_id, Memory.status == "active")
                .group_by(Memory.type)
            )
        }
        flags = self.session.execute(
            select(
                func.coalesce(func.sum(case((Memory.is_pinned, 1), else_=0)), 0),
                func.coalesce(func.sum(case((Memory.is_locked, 1), else_=0)), 0),
            ).where(Memory.project_id == project_id, Memory.status == "active")
        ).one()
        return MemoryCounts(by_type=by_type, pinned=flags[0], locked=flags[1])

    def history(self, project_id: str, ref: str) -> MemoryHistory:
        """The full replacement chain around a memory, oldest first."""
        memory = self.get(project_id, ref)
        chain = [memory]
        while chain[0].supersedes_id:
            chain.insert(0, self._by_id(project_id, chain[0].supersedes_id))
        while True:
            nxt = self.session.scalar(
                select(Memory).where(
                    Memory.project_id == project_id, Memory.supersedes_id == chain[-1].id
                )
            )
            if nxt is None:
                break
            chain.append(nxt)
        return MemoryHistory(
            chain=[MemoryRef.model_validate(m) for m in chain], current_id=chain[-1].id
        )

    # ---- writes -----------------------------------------------------------------------

    def create(self, project_id: str, payload: MemoryCreate, actor: str = HUMAN) -> MemoryRead:
        self.projects.get(project_id)
        if payload.is_locked and actor != HUMAN:
            raise locked("Only a person can lock a memory")
        now = datetime.now(UTC)
        memory = Memory(
            project_id=project_id,
            human_id=self._next_human_id(project_id, payload.type),
            type=payload.type,
            title=payload.title,
            content=payload.content,
            importance=payload.importance,
            ai_visibility=payload.ai_visibility,
            is_pinned=payload.is_pinned,
            is_locked=payload.is_locked,
            is_resolved=payload.is_resolved,
            source_type=payload.source_type or (None if actor == HUMAN else "agent"),
            source_reference=payload.source_reference or (None if actor == HUMAN else actor),
            confidence=payload.confidence,
            created_at=now,
            updated_at=now,
        )
        self.session.add(memory)
        self.session.flush()
        self._set_tags(memory, payload.tags)
        self._set_tasks(memory, payload.task_ids)
        for ref in payload.related:
            self._add_link(memory, self.get(project_id, ref), actor)
        self._log_memory(memory, "MEMORY_CREATED", actor)
        self.session.commit()
        return self.read(project_id, memory.id)

    def update(
        self, project_id: str, ref: str, payload: MemoryUpdate, actor: str = HUMAN
    ) -> MemoryRead:
        memory = self.get(project_id, ref)
        changes = payload.model_dump(exclude_unset=True)
        requested_fields = set(changes)
        was_locked = memory.is_locked
        tags, task_ids = changes.pop("tags", None), changes.pop("task_ids", None)
        if "is_locked" in changes and actor != HUMAN:
            raise locked("Only a person can lock or unlock a memory")
        # Unlocking and editing in one request is fine for a person; the lock is theirs.
        if memory.is_locked and actor != HUMAN and PROTECTED_FIELDS & requested_fields:
            raise self._locked_error(memory)
        if memory.status in ("superseded", "invalidated") and PROTECTED_FIELDS & requested_fields:
            raise conflict(f"{memory.human_id} is {memory.status}; its text is kept as history")
        for field, value in changes.items():
            setattr(memory, field, value)
        if tags is not None:
            self._set_tags(memory, tags)
        if task_ids is not None:
            self._set_tasks(memory, task_ids)
        memory.updated_at = datetime.now(UTC)
        event_type = (
            "MEMORY_LOCKED"
            if not was_locked and memory.is_locked
            else "MEMORY_UNLOCKED"
            if was_locked and not memory.is_locked
            else "MEMORY_UPDATED"
        )
        self._log_memory(memory, event_type, actor, {"changed_fields": sorted(requested_fields)})
        self.session.commit()
        return self.read(project_id, memory.id)

    def supersede(
        self, project_id: str, ref: str, payload: MemorySupersede, actor: str = HUMAN
    ) -> MemoryRead:
        old = self.get(project_id, ref)
        self._require_unlocked(old, actor)
        if old.status != "active":
            raise conflict(f"{old.human_id} is {old.status} and cannot be replaced")
        if payload.is_locked and actor != HUMAN:
            raise locked("Only a person can lock a memory")
        now = datetime.now(UTC)
        new = Memory(
            project_id=project_id,
            human_id=self._next_human_id(project_id, old.type),
            type=old.type,
            title=payload.title,
            content=payload.content,
            importance=payload.importance or old.importance,
            ai_visibility=payload.ai_visibility or old.ai_visibility,
            is_pinned=old.is_pinned,
            is_locked=old.is_locked if payload.is_locked is None else payload.is_locked,
            source_type=None if actor == HUMAN else "agent",
            source_reference=None if actor == HUMAN else actor,
            created_at=now,
            updated_at=now,
        )
        self.session.add(new)
        self.session.flush()
        # Link the old record first: the one-successor constraint guards double replacement.
        new.supersedes_id = old.id
        old.status = "superseded"
        old.is_pinned = False
        old.updated_at = now
        self._copy_links(old, new)
        self._log_memory(new, "MEMORY_CREATED", actor, {"supersedes_human_id": old.human_id})
        self._log_memory(old, "MEMORY_SUPERSEDED", actor, {"replacement_human_id": new.human_id})
        self._commit_conflict("This memory was already replaced")
        return self.read(project_id, new.id)

    def invalidate(self, project_id: str, ref: str, actor: str = HUMAN) -> MemoryRead:
        """Mark a memory as wrong. It stays in history but is never offered to agents."""
        memory = self.get(project_id, ref)
        self._require_unlocked(memory, actor)
        if memory.status in ("superseded", "invalidated"):
            raise conflict(f"{memory.human_id} is already {memory.status}")
        now = datetime.now(UTC)
        memory.status, memory.invalidated_at, memory.updated_at = "invalidated", now, now
        memory.archived_at = None
        self._log_memory(memory, "MEMORY_INVALIDATED", actor)
        self.session.commit()
        return self.read(project_id, memory.id)

    def archive(self, project_id: str, ref: str, actor: str = HUMAN) -> MemoryRead:
        memory = self.get(project_id, ref)
        self._require_unlocked(memory, actor)
        if memory.status != "active":
            raise conflict(f"{memory.human_id} is {memory.status} and cannot be archived")
        now = datetime.now(UTC)
        memory.status, memory.archived_at, memory.updated_at = "archived", now, now
        self._log_memory(memory, "MEMORY_ARCHIVED", actor)
        self.session.commit()
        return self.read(project_id, memory.id)

    def restore(self, project_id: str, ref: str, actor: str = HUMAN) -> MemoryRead:
        memory = self.get(project_id, ref)
        if memory.status not in ("archived", "invalidated"):
            raise conflict(f"{memory.human_id} is {memory.status} and cannot be restored")
        self._require_unlocked(memory, actor)
        memory.status = "active"
        memory.archived_at = memory.invalidated_at = None
        memory.updated_at = datetime.now(UTC)
        self._log_memory(memory, "MEMORY_RESTORED", actor)
        self.session.commit()
        return self.read(project_id, memory.id)

    def link(self, project_id: str, ref: str, related: str, actor: str = HUMAN) -> MemoryRead:
        """Connect two memories of one project. Links describe memory; locks do not block them."""
        memory = self.get(project_id, ref)
        if self._add_link(memory, self.get(project_id, related), actor):
            self._log_memory(memory, "MEMORY_LINKED", actor)
        self.session.commit()
        return self.read(project_id, memory.id)

    def unlink(self, project_id: str, ref: str, related: str, actor: str = HUMAN) -> MemoryRead:
        memory, other = self.get(project_id, ref), self.get(project_id, related)
        low, high = sorted((memory.id, other.id))
        link = self.session.get(MemoryLink, (low, high))
        if link is not None:
            self.session.delete(link)
            self._log_memory(memory, "MEMORY_UNLINKED", actor)
        self.session.commit()
        return self.read(project_id, memory.id)

    def delete(self, project_id: str, ref: str, actor: str = HUMAN) -> None:
        """Permanent removal, for mistakes. Locked records must be unlocked first."""
        memory = self.get(project_id, ref)
        if actor != HUMAN:
            raise locked("Only a person can permanently delete a memory")
        if memory.is_locked:
            raise locked(f"{memory.human_id} is locked. Unlock it before deleting it.")
        if memory.supersedes_id or self.session.scalar(
            select(Memory.id).where(Memory.supersedes_id == memory.id)
        ):
            raise conflict(
                f"{memory.human_id} belongs to a replacement history and is kept as history"
            )
        self._log_memory(memory, "MEMORY_DELETED", actor)
        self.session.delete(memory)
        self.session.commit()

    # ---- internals --------------------------------------------------------------------

    def _add_link(self, memory: Memory, other: Memory, actor: str) -> bool:
        if memory.id == other.id:
            raise conflict("A memory cannot be linked to itself")
        low, high = sorted((memory.id, other.id))
        if self.session.get(MemoryLink, (low, high)) is not None:
            return False
        self.session.add(
            MemoryLink(
                memory_id=low,
                related_id=high,
                project_id=memory.project_id,
                created_by=actor,
                created_at=datetime.now(UTC),
            )
        )
        self.session.flush()
        return True

    def _log_memory(
        self, memory: Memory, event_type: str, actor: str, metadata: dict | None = None
    ) -> None:
        known_actor = actor.lower() if actor.lower() in {"human", "codex", "claude"} else "system"
        ActivityService(self.session).record(
            memory.project_id,
            event_type,
            actor_type=known_actor,
            actor_name=None if known_actor == actor.lower() else actor,
            entity_type="memory",
            entity_id=memory.id,
            metadata={
                "title": memory.title,
                "human_id": memory.human_id,
                "type": memory.type,
                **(metadata or {}),
            },
        )

    @staticmethod
    def _locked_error(memory: Memory):
        return locked(
            f"{memory.human_id} is locked. Propose a change for a person to review instead."
        )

    def _require_unlocked(self, memory: Memory, actor: str) -> None:
        if memory.is_locked and actor != HUMAN:
            raise self._locked_error(memory)

    def _by_id(self, project_id: str, memory_id: str) -> Memory:
        memory = self.session.scalar(
            select(Memory).where(Memory.id == memory_id, Memory.project_id == project_id)
        )
        if memory is None:
            raise not_found("Memory not found in this project")
        return memory

    def _next_human_id(self, project_id: str, memory_type: str) -> str:
        prefix = TYPE_PREFIXES[memory_type]
        existing = self.session.scalars(
            select(Memory.human_id).where(
                Memory.project_id == project_id, Memory.human_id.like(f"{prefix}-%")
            )
        )
        highest = max((int(h.rsplit("-", 1)[1]) for h in existing), default=0)
        return f"{prefix}-{highest + 1:03d}"

    def _set_tags(self, memory: Memory, names: list[str]) -> None:
        wanted_ids = ensure_tags(self.session, memory.project_id, names)
        current = {
            link.tag_id: link
            for link in self.session.scalars(
                select(MemoryTag).where(MemoryTag.memory_id == memory.id)
            )
        }
        for tag_id, link in current.items():
            if tag_id not in wanted_ids:
                self.session.delete(link)
        for tag_id in wanted_ids - current.keys():
            self.session.add(
                MemoryTag(memory_id=memory.id, tag_id=tag_id, project_id=memory.project_id)
            )

    def _set_tasks(self, memory: Memory, task_refs: list[str]) -> None:
        wanted = {self.tasks.get(memory.project_id, ref).id for ref in task_refs}
        current = {
            link.task_id: link
            for link in self.session.scalars(
                select(MemoryTask).where(MemoryTask.memory_id == memory.id)
            )
        }
        for task_id, link in current.items():
            if task_id not in wanted:
                self.session.delete(link)
        for task_id in wanted - current.keys():
            self.session.add(
                MemoryTask(memory_id=memory.id, task_id=task_id, project_id=memory.project_id)
            )

    def _copy_links(self, old: Memory, new: Memory) -> None:
        for tag_id in self.session.scalars(
            select(MemoryTag.tag_id).where(MemoryTag.memory_id == old.id)
        ):
            self.session.add(MemoryTag(memory_id=new.id, tag_id=tag_id, project_id=new.project_id))
        for task_id in self.session.scalars(
            select(MemoryTask.task_id).where(MemoryTask.memory_id == old.id)
        ):
            self.session.add(
                MemoryTask(memory_id=new.id, task_id=task_id, project_id=new.project_id)
            )
        # A replacement keeps the old record's connections; the old record keeps its own as history.
        for link in self.session.scalars(
            select(MemoryLink).where(
                or_(MemoryLink.memory_id == old.id, MemoryLink.related_id == old.id)
            )
        ).all():
            other_id = link.related_id if link.memory_id == old.id else link.memory_id
            if other_id != new.id:
                self._add_link(new, self._by_id(new.project_id, other_id), "system")
        for file_id in self.session.scalars(
            select(FileMemory.file_id).where(FileMemory.memory_id == old.id)
        ):
            self.session.add(
                FileMemory(file_id=file_id, memory_id=new.id, project_id=new.project_id)
            )
        self._copy_typed_links(old, new)

    def _copy_typed_links(self, old: Memory, new: Memory) -> None:
        """Typed links follow the record too: what the old one caused, used or explained, the
        new one does. Guesses stay behind; discovery looks at the new wording afresh."""
        from app.services.graph import PROVENANCE_KEEP

        rows = self.session.scalars(
            select(DataLink).where(
                DataLink.status.in_(("active", "weak")),
                DataLink.relationship != "supersedes",
                or_(
                    (DataLink.source_kind == "memory") & (DataLink.source_id == old.id),
                    (DataLink.target_kind == "memory") & (DataLink.target_id == old.id),
                ),
            )
        ).all()
        now = datetime.now(UTC)
        moved = {("memory", old.id): ("memory", new.id)}
        for row in rows:
            source = (row.source_kind, row.source_id)
            target = (row.target_kind, row.target_id)
            source, target = moved.get(source, source), moved.get(target, target)
            if row.relationship == "relates_to" and source[0] == target[0] == "memory":
                source, target = sorted((source, target))  # low to high, like memory links
            if source == target or self.session.scalar(
                select(DataLink.id).where(
                    DataLink.source_kind == source[0],
                    DataLink.source_id == source[1],
                    DataLink.target_kind == target[0],
                    DataLink.target_id == target[1],
                    DataLink.relationship == row.relationship,
                )
            ):
                continue
            entry = {
                "source": "replacement",
                "detail": f"carried over from {old.human_id} when it was replaced",
                "at": now.isoformat(),
            }
            self.session.add(
                DataLink(
                    project_id=row.project_id,
                    source_kind=source[0],
                    source_id=source[1],
                    target_kind=target[0],
                    target_id=target[1],
                    relationship=row.relationship,
                    strength=row.strength,
                    confidence=row.confidence,
                    created_by=row.created_by,
                    actor=row.actor,
                    status=row.status,
                    note=row.note,
                    contextual_weights=dict(row.contextual_weights or {}),
                    provenance=[*(row.provenance or []), entry][-PROVENANCE_KEEP:],
                    success_count=row.success_count,
                    failure_count=row.failure_count,
                    created_at=now,
                    updated_at=now,
                )
            )
        self.session.flush()

    def _reads(self, memories: list[Memory]) -> list[MemoryRead]:
        if not memories:
            return []
        ids = [m.id for m in memories]
        tags: dict[str, list[str]] = defaultdict(list)
        for memory_id, name in self.session.execute(
            select(MemoryTag.memory_id, Tag.name)
            .join(Tag, Tag.id == MemoryTag.tag_id)
            .where(MemoryTag.memory_id.in_(ids))
            .order_by(Tag.name_key)
        ):
            tags[memory_id].append(name)
        tasks: dict[str, list[TaskRef]] = defaultdict(list)
        for memory_id, task in self.session.execute(
            select(MemoryTask.memory_id, Task)
            .join(Task, Task.id == MemoryTask.task_id)
            .where(MemoryTask.memory_id.in_(ids))
            .order_by(Task.human_id)
        ):
            tasks[memory_id].append(TaskRef.model_validate(task))
        predecessor_ids = [m.supersedes_id for m in memories if m.supersedes_id]
        related = {
            m.id: m
            for m in self.session.scalars(
                select(Memory).where(
                    or_(Memory.id.in_(predecessor_ids), Memory.supersedes_id.in_(ids))
                )
            )
        }
        successors = {m.supersedes_id: m for m in related.values() if m.supersedes_id in ids}
        links: dict[str, list[MemoryRef]] = defaultdict(list)
        pairs = self.session.execute(
            select(MemoryLink.memory_id, MemoryLink.related_id).where(
                or_(MemoryLink.memory_id.in_(ids), MemoryLink.related_id.in_(ids))
            )
        ).all()
        others = {
            m.id: m
            for m in self.session.scalars(
                select(Memory).where(Memory.id.in_({a for a, _ in pairs} | {b for _, b in pairs}))
            )
        }
        for a, b in pairs:
            for mine, theirs in ((a, b), (b, a)):
                if mine in ids and theirs in others:
                    links[mine].append(MemoryRef.model_validate(others[theirs]))
        images = ImageService(self.session).for_records("memory", ids)
        result = []
        for memory in memories:
            read = MemoryRead.model_validate(memory)
            read.tags = tags.get(memory.id, [])
            read.images = images[memory.id]
            read.tasks = tasks.get(memory.id, [])
            read.related = sorted(links.get(memory.id, []), key=lambda ref: ref.human_id)
            if memory.supersedes_id in related:
                read.supersedes = MemoryRef.model_validate(related[memory.supersedes_id])
            if memory.id in successors:
                read.superseded_by = MemoryRef.model_validate(successors[memory.id])
            result.append(read)
        return result

    def _commit_conflict(self, message: str) -> None:
        from sqlalchemy.exc import IntegrityError

        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise conflict(message) from exc

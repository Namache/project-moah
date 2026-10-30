"""The Link System: one graph over records the app already stores.

Nodes are references to existing records. Edges come from two places:
- built-in links: relationships the app already keeps in its own tables (task relationships,
  memory links, memory-task links, file links, supersession, milestones), read with a default
  type and strength and never copied;
- ``data_links``: typed links made by a person or an agent. A stored link for the same pair
  and relationship as a built-in one overrides its strength, confidence and status.

Every edge is stored in one direction and read in both: from the far end it carries the
inverse name (``uses`` / ``used_by``).

Scope rule: both ends of a link belong to one project. Traversal reads one project only.
"""

from __future__ import annotations

import heapq
import random
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.checkpoint import Checkpoint
from app.models.files import FileCheckpoint, FileMemory, FileTask, ProjectFile
from app.models.graph import INVERSES, NEGATIVE, NODE_KINDS, RELATIONSHIPS, DataLink
from app.models.memory import TYPE_PREFIXES, Memory, MemoryLink, MemoryTask
from app.models.project import GLOBAL_PROJECT_ID, utc_now
from app.models.task import Milestone, Task, TaskRelationship
from app.schemas.graph import LinkRead, NodeLinks, NodeRead, RelationshipType
from app.schemas.memory import HUMAN
from app.services.activity import ActivityService
from app.services.errors import conflict, invalid, not_found
from app.services.projects import ProjectService

# Default strength and confidence of built-in links, by origin.
BUILTIN_STRENGTH = {
    "task_part_of": 0.8,
    "task_depends_on": 0.7,
    "task_related_to": 0.4,
    "task_supersedes": 0.9,
    "memory_supersedes": 0.9,
    "memory_task": 0.7,
    "memory_link": 0.5,
    "file_task": 0.6,
    "file_memory": 0.5,
    "file_checkpoint": 0.3,
    "checkpoint_task": 0.4,
    "milestone_task": 0.6,
}
DEFAULT_STRENGTH = 0.5
# How each built-in link came to exist, for provenance.
BUILTIN_SOURCES = {
    "task_part_of": "task relationship (subtask)",
    "task_depends_on": "task relationship (depends on)",
    "task_related_to": "task relationship (related)",
    "task_supersedes": "task relationship (replaces)",
    "memory_supersedes": "memory replacement history",
    "memory_task": "memory linked to the task",
    "memory_link": "connected memories",
    "file_task": "file notes linked to the task",
    "file_memory": "file notes linked to the memory",
    "file_checkpoint": "file named in a checkpoint",
    "checkpoint_task": "checkpoint recorded for the task",
    "milestone_task": "task in the milestone",
}
# Every further hop multiplies the path by this, so long chains need strong links to count.
HOP_DECAY = 0.85
STRENGTH_FLOOR, STRENGTH_CEILING = 0.05, 0.98
WEAK_BELOW = 0.25
PROVENANCE_KEEP = 12
# Links from a person are trusted fully; links from agents a little less.
DEFAULT_CONFIDENCE = {"user": 1.0, "system": 0.8, "inferred": 0.5, "imported": 0.7}
# A guessed link that proved useful in real work is trusted like one learned from use.
LEARNED_CONFIDENCE = 0.6
TRAVERSABLE_STATUSES = ("active", "weak")
# Personalized PageRank (push): relevance flows out of the starting nodes along links and is
# added up over every route, so a record two good routes reach outranks one a single route
# reaches. A node with more link weight than this shares its relevance out among its links,
# so a record linked to everything (a hub) passes little to each one.
HUB_WEIGHT = 5.0
PUSH_EPSILON = 0.01  # relevance under this is not passed on
PUSH_LIMIT = 400  # pushes per walk: bounds the work whatever the graph's size
# Thompson sampling: a link's learned strength is the mean of a Beta distribution whose spread
# shrinks as feedback piles up. Sampling from it gives untried links an occasional chance to
# prove themselves, while links with a long record behave almost as their mean.
PRIOR_OBSERVATIONS = 10  # a link with no feedback yet counts as 10 imagined uses
INACTIVE_MEMORY = ("superseded", "invalidated", "archived")
MEMORY_PREFIXES = {prefix for prefix in TYPE_PREFIXES.values()}
REF_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9]{0,9}-\d{1,6}")
# An ID named in running text. It must stand alone ("R-32da" names nothing), and "global RULE-3"
# or "global:RULE-3" names the Global record, the way the brief prints the person's rules.
MENTION_PATTERN = re.compile(
    r"(?:(?P<scope>\bglobal)[ \t]*:?[ \t]*)?"
    r"(?<![\w-])(?P<ref>[A-Za-z][A-Za-z0-9]{0,9}-\d{1,6})(?![\w-])",
    re.IGNORECASE,
)
# The most words a relationship name takes when written with spaces ("must not depend on").
RELATIONSHIP_WORDS = 4


@dataclass(frozen=True, order=True)
class Node:
    kind: str
    id: str


@dataclass
class NodeInfo:
    node: Node
    label: str  # a short handle people recognise: PB-12, DEC-003, a path, a shelf name
    title: str
    subtype: str | None = None  # memory type, for memory
    status: str | None = None
    # False for records retrieval must never reach (superseded, hidden, archived...).
    retrievable: bool = True
    # "global" for a Global record seen from a project through a route; None otherwise.
    scope: str | None = None


@dataclass
class Edge:
    source: Node
    target: Node
    relationship: str
    strength: float
    confidence: float
    origin: str  # "link" for data_links rows, otherwise the built-in origin key
    status: str = "active"
    created_by: str = "system"
    link_id: str | None = None
    note: str | None = None
    contextual_weights: dict[str, float] = field(default_factory=dict)
    provenance: list[dict] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0

    @property
    def key(self) -> tuple[Node, Node, str]:
        return (self.source, self.target, self.relationship)

    def other(self, node: Node) -> Node:
        return self.target if node == self.source else self.source

    def read_from(self, node: Node) -> str:
        """The relationship as seen from ``node``: forward from the source, inverse otherwise."""
        return self.relationship if node == self.source else RELATIONSHIPS[self.relationship][0]

    @property
    def weight(self) -> float:
        return self.strength * self.confidence

    def strength_for(self, operation: str | None) -> float:
        """Contextual strength for this kind of work when it has been learned, else base."""
        if operation and operation in self.contextual_weights:
            return self.contextual_weights[operation]
        return self.strength

    def weight_for(self, operation: str | None) -> float:
        return self.strength_for(operation) * self.confidence


@dataclass
class Path:
    """The best route found to a node: its score and the hops that led there."""

    node: Node
    score: float
    hops: list[tuple[Node, str, Edge]] = field(default_factory=list)  # (from, read-as, edge)

    @property
    def depth(self) -> int:
        return len(self.hops)


def normalize_relationship(name: str) -> tuple[str, bool]:
    """A relationship name -> (stored name, whether the endpoints must be swapped)."""
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    if key in RELATIONSHIPS:
        return key, False
    if key in INVERSES:
        forward = INVERSES[key]
        # Symmetric relationships are their own inverse; no swap needed.
        return forward, RELATIONSHIPS[forward][0] != forward
    raise invalid(f"{name!r} is not a known relationship")


class GraphService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.projects = ProjectService(session)
        self.activity = ActivityService(session)

    # ---- nodes --------------------------------------------------------------------------

    def resolve(self, project_id: str, ref: str, *, allow_global: bool = False) -> Node:
        """``kind:value`` (task:PB-12, memory:DEC-3, file:src/a.py, shelf:Inventory) or a bare
        human ID. A bare ID with a memory prefix (DEC, RULE, ...) is memory, otherwise a task.

        With ``allow_global``, ``global:RULE-3`` names a Global record, and a bare memory ID
        that this project lacks falls back to the Global one. Only Global records can be
        reached from a project this way; another project's records never can."""
        ref = ref.strip()
        if allow_global and project_id != GLOBAL_PROJECT_ID:
            head, _, rest = ref.partition(":")
            if head.lower() == "global" and rest:
                return Node("memory", self._resolve_id(GLOBAL_PROJECT_ID, "memory", rest.strip()))
            try:
                return self.resolve(project_id, ref)
            except Exception:
                node = self.resolve(GLOBAL_PROJECT_ID, ref)
                if node.kind != "memory":
                    raise
                return node
        kind, _, value = ref.partition(":")
        if value and kind.lower() in NODE_KINDS:
            kind = kind.lower()
        else:
            kind, value = "", ref
        if not kind:
            if not REF_PATTERN.fullmatch(value):
                raise invalid(f"{ref!r} is not a node reference; use kind:value, e.g. task:PB-12")
            kind = "memory" if value.split("-")[0].upper() in MEMORY_PREFIXES else "task"
        return Node(kind, self._resolve_id(project_id, kind, value.strip()))

    def _resolve_id(self, project_id: str, kind: str, value: str) -> str:
        # Imported lazily: these services import the context engine's neighbours.
        if kind == "task":
            from app.services.tasks import TaskService

            return TaskService(self.session).get(project_id, value).id
        if kind == "memory":
            from app.services.memory import MemoryService

            return MemoryService(self.session).get(project_id, value).id
        if kind == "file":
            from app.services.files import FileService

            return FileService(self.session).get(project_id, value).id
        if kind == "shelf":
            from app.services.shelves import ShelfService

            return ShelfService(self.session).get(project_id, value).id
        model = {"checkpoint": Checkpoint, "milestone": Milestone}[kind]
        found = self.session.scalar(
            select(model.id).where(model.project_id == project_id, model.id == value)
        )
        if found is None:
            self.projects.get(project_id)
            raise not_found(f"No {kind} {value} in this project")
        return found

    def describe(self, project_id: str, nodes: Iterable[Node]) -> dict[Node, NodeInfo]:
        """Labels and state for many nodes at once, one query per kind. Unknown nodes are
        left out, so a caller can treat a missing entry as gone."""
        by_kind: dict[str, set[str]] = {}
        for n in nodes:
            by_kind.setdefault(n.kind, set()).add(n.id)
        out: dict[Node, NodeInfo] = {}
        if ids := by_kind.get("task"):
            for t in self.session.scalars(
                select(Task).where(Task.project_id == project_id, Task.id.in_(ids))
            ):
                n = Node("task", t.id)
                out[n] = NodeInfo(n, t.human_id, t.title, status=t.status)
        if ids := by_kind.get("memory"):
            for m in self.session.scalars(
                select(Memory).where(Memory.project_id == project_id, Memory.id.in_(ids))
            ):
                n = Node("memory", m.id)
                out[n] = NodeInfo(
                    n,
                    m.human_id,
                    m.title,
                    subtype=m.type,
                    status=m.status,
                    retrievable=m.status not in INACTIVE_MEMORY and m.ai_visibility != "hidden",
                )
            # A route from this project can end at a Global record (never another project's).
            rest = ids - {n.id for n in out if n.kind == "memory"}
            if rest and project_id != GLOBAL_PROJECT_ID:
                for m in self.session.scalars(
                    select(Memory).where(
                        Memory.project_id == GLOBAL_PROJECT_ID, Memory.id.in_(rest)
                    )
                ):
                    n = Node("memory", m.id)
                    out[n] = NodeInfo(
                        n,
                        f"{m.human_id} (global)",
                        m.title,
                        subtype=m.type,
                        status=m.status,
                        retrievable=m.status not in INACTIVE_MEMORY
                        and m.ai_visibility not in ("hidden", "manual_only"),
                        scope="global",
                    )
        if ids := by_kind.get("file"):
            for f in self.session.scalars(
                select(ProjectFile).where(
                    ProjectFile.project_id == project_id, ProjectFile.id.in_(ids)
                )
            ):
                n = Node("file", f.id)
                out[n] = NodeInfo(n, f.path, f.purpose or f.path)
        if ids := by_kind.get("checkpoint"):
            for c in self.session.scalars(
                select(Checkpoint).where(
                    Checkpoint.project_id == project_id, Checkpoint.id.in_(ids)
                )
            ):
                n = Node("checkpoint", c.id)
                out[n] = NodeInfo(n, "Checkpoint", c.title)
        if ids := by_kind.get("milestone"):
            for ms in self.session.scalars(
                select(Milestone).where(Milestone.project_id == project_id, Milestone.id.in_(ids))
            ):
                n = Node("milestone", ms.id)
                out[n] = NodeInfo(n, ms.name, ms.name, status=ms.status)
        if ids := by_kind.get("shelf"):
            from app.models.graph import Shelf

            for s in self.session.scalars(
                select(Shelf).where(Shelf.project_id == project_id, Shelf.id.in_(ids))
            ):
                n = Node("shelf", s.id)
                out[n] = NodeInfo(n, s.name, s.description or s.name)
        return out

    # ---- edges --------------------------------------------------------------------------

    def edges(self, project_id: str, nodes: Iterable[Node]) -> list[Edge]:
        """Every edge touching any of ``nodes``: built-in links, overridden or extended by
        stored links. Edges of every status are returned; callers filter."""
        nodes = set(nodes)
        found: dict[tuple[Node, Node, str], Edge] = {
            e.key: e for e in self._builtin_edges(project_id, nodes)
        }
        for e in self._stored_edges(project_id, nodes):
            builtin = found.get(e.key)
            if builtin is not None:
                e.origin = builtin.origin  # an override keeps the built-in's origin
                e.provenance = builtin.provenance + e.provenance
            found[e.key] = e
        return list(found.values())

    def neighbours(self, project_id: str, node: Node) -> list[tuple[Edge, Node, str]]:
        """(edge, other end, relationship as read from ``node``), strongest first."""
        out = [(e, e.other(node), e.read_from(node)) for e in self.edges(project_id, [node])]
        return sorted(out, key=lambda x: (-x[0].weight, x[2]))

    def _stored_edges(self, project_id: str, nodes: set[Node]) -> list[Edge]:
        if not nodes:
            return []
        conditions = []
        for kind in {n.kind for n in nodes}:
            ids = [n.id for n in nodes if n.kind == kind]
            conditions.append((DataLink.source_kind == kind) & DataLink.source_id.in_(ids))
            conditions.append((DataLink.target_kind == kind) & DataLink.target_id.in_(ids))
        rows = self.session.scalars(
            select(DataLink).where(DataLink.project_id == project_id, or_(*conditions))
        )
        return [self._edge(row) for row in rows]

    @staticmethod
    def _edge(row: DataLink) -> Edge:
        return Edge(
            Node(row.source_kind, row.source_id),
            Node(row.target_kind, row.target_id),
            row.relationship,
            row.strength,
            row.confidence,
            "link",
            status=row.status,
            created_by=row.created_by,
            link_id=row.id,
            note=row.note,
            contextual_weights=dict(row.contextual_weights or {}),
            provenance=list(row.provenance or []),
            success_count=row.success_count,
            failure_count=row.failure_count,
        )

    def _builtin_edges(self, project_id: str, nodes: set[Node]) -> list[Edge]:
        ids = {kind: [n.id for n in nodes if n.kind == kind] for kind in NODE_KINDS}
        edges: list[Edge] = []

        def add(source: Node, target: Node, relationship: str, origin: str) -> None:
            edges.append(
                Edge(
                    source,
                    target,
                    relationship,
                    BUILTIN_STRENGTH[origin],
                    1.0,
                    origin,
                    provenance=[{"source": "built-in", "detail": BUILTIN_SOURCES[origin]}],
                )
            )

        if tasks := ids["task"]:
            for r in self.session.scalars(
                select(TaskRelationship).where(
                    TaskRelationship.project_id == project_id,
                    or_(
                        TaskRelationship.source_task_id.in_(tasks),
                        TaskRelationship.target_task_id.in_(tasks),
                    ),
                )
            ):
                s, t = Node("task", r.source_task_id), Node("task", r.target_task_id)
                if r.type == "parent":  # stored on the subtask, pointing at its parent
                    add(t, s, "contains", "task_part_of")
                elif r.type == "depends_on":
                    add(s, t, "depends_on", "task_depends_on")
                elif r.type == "related_to":
                    add(s, t, "relates_to", "task_related_to")
                elif r.type == "supersedes":
                    add(s, t, "supersedes", "task_supersedes")
            for row in self.session.execute(
                select(Task.id, Task.milestone_id).where(
                    Task.project_id == project_id,
                    Task.id.in_(tasks),
                    Task.milestone_id.is_not(None),
                )
            ):
                add(
                    Node("milestone", row.milestone_id),
                    Node("task", row.id),
                    "contains",
                    "milestone_task",
                )
            for row in self.session.execute(
                select(Checkpoint.id, Checkpoint.task_id).where(
                    Checkpoint.project_id == project_id, Checkpoint.task_id.in_(tasks)
                )
            ):
                add(
                    Node("checkpoint", row.id),
                    Node("task", row.task_id),
                    "references",
                    "checkpoint_task",
                )
        if milestones := ids["milestone"]:
            for row in self.session.execute(
                select(Task.id, Task.milestone_id).where(
                    Task.project_id == project_id, Task.milestone_id.in_(milestones)
                )
            ):
                add(
                    Node("milestone", row.milestone_id),
                    Node("task", row.id),
                    "contains",
                    "milestone_task",
                )
        if checkpoints := ids["checkpoint"]:
            for row in self.session.execute(
                select(Checkpoint.id, Checkpoint.task_id).where(
                    Checkpoint.project_id == project_id,
                    Checkpoint.id.in_(checkpoints),
                    Checkpoint.task_id.is_not(None),
                )
            ):
                add(
                    Node("checkpoint", row.id),
                    Node("task", row.task_id),
                    "references",
                    "checkpoint_task",
                )
        if tasks or ids["memory"]:
            memory_ids = ids["memory"]
            for row in self.session.scalars(
                select(MemoryTask).where(
                    MemoryTask.project_id == project_id,
                    or_(MemoryTask.task_id.in_(tasks), MemoryTask.memory_id.in_(memory_ids)),
                )
            ):
                add(
                    Node("memory", row.memory_id),
                    Node("task", row.task_id),
                    "applies_to",
                    "memory_task",
                )
        if memory_ids := ids["memory"]:
            for row in self.session.scalars(
                select(MemoryLink).where(
                    MemoryLink.project_id == project_id,
                    or_(
                        MemoryLink.memory_id.in_(memory_ids),
                        MemoryLink.related_id.in_(memory_ids),
                    ),
                )
            ):
                add(
                    Node("memory", row.memory_id),
                    Node("memory", row.related_id),
                    "relates_to",
                    "memory_link",
                )
            for row in self.session.execute(
                select(Memory.id, Memory.supersedes_id).where(
                    Memory.project_id == project_id,
                    Memory.supersedes_id.is_not(None),
                    or_(Memory.id.in_(memory_ids), Memory.supersedes_id.in_(memory_ids)),
                )
            ):
                add(
                    Node("memory", row.id),
                    Node("memory", row.supersedes_id),
                    "supersedes",
                    "memory_supersedes",
                )
        files = ids["file"]
        if tasks or files:
            for row in self.session.scalars(
                select(FileTask).where(
                    FileTask.project_id == project_id,
                    or_(FileTask.task_id.in_(tasks), FileTask.file_id.in_(files)),
                )
            ):
                add(Node("task", row.task_id), Node("file", row.file_id), "affects", "file_task")
        if ids["memory"] or files:
            for row in self.session.scalars(
                select(FileMemory).where(
                    FileMemory.project_id == project_id,
                    or_(FileMemory.memory_id.in_(ids["memory"]), FileMemory.file_id.in_(files)),
                )
            ):
                add(
                    Node("memory", row.memory_id),
                    Node("file", row.file_id),
                    "references",
                    "file_memory",
                )
        if ids["checkpoint"] or files:
            for row in self.session.scalars(
                select(FileCheckpoint).where(
                    FileCheckpoint.project_id == project_id,
                    or_(
                        FileCheckpoint.checkpoint_id.in_(ids["checkpoint"]),
                        FileCheckpoint.file_id.in_(files),
                    ),
                )
            ):
                add(
                    Node("checkpoint", row.checkpoint_id),
                    Node("file", row.file_id),
                    "references",
                    "file_checkpoint",
                )
        # One edge per key: a pair reached from both ends is read twice above.
        return list({e.key: e for e in edges}.values())

    # ---- writing links ------------------------------------------------------------------

    def link(
        self,
        project_id: str,
        source: str,
        relationship: str,
        target: str,
        *,
        strength: float | None = None,
        confidence: float | None = None,
        status: str | None = None,
        note: str | None = None,
        created_by: str = "user",
        actor: str = HUMAN,
    ) -> Edge:
        """Create a typed link, or change the one that already exists for this pair.

        Inverse names are accepted (``used_by``) and stored as the forward type with the
        endpoints swapped. Changing a built-in link stores an override for it."""
        stored, swap = normalize_relationship(relationship)
        a = self.resolve(project_id, source, allow_global=True)
        b = self.resolve(project_id, target, allow_global=True)
        if swap:
            a, b = b, a
        if a == b:
            raise conflict("A record cannot be linked to itself")
        scopes = self.describe(project_id, [a, b])
        if all(scopes[n].scope == "global" for n in (a, b) if n in scopes):
            raise invalid("Both records are Global; link them in the Global scope instead")
        for value, name in ((strength, "strength"), (confidence, "confidence")):
            if value is not None and not 0 <= value <= 1:
                raise invalid(f"{name} must be between 0 and 1")
        row = self.find_link(project_id, f"{a.kind}:{a.id}", stored, f"{b.kind}:{b.id}")
        builtin = next(
            (e for e in self._builtin_edges(project_id, {a}) if e.key == (a, b, stored)), None
        )
        if row is None:
            row = self._new_row(project_id, a, b, stored, builtin, created_by, actor)
            event = "LINK_CREATED"
        else:
            event = "LINK_UPDATED"
            if row.status in ("candidate", "rejected") and status is None:
                # Asserting an inferred or rejected link confirms it.
                row.status = "active"
                row.confidence = max(row.confidence, DEFAULT_CONFIDENCE[created_by])
                event = "LINK_CONFIRMED"
        self._add_provenance(
            row,
            "person" if created_by == "user" else created_by,
            "made by a person" if actor == HUMAN else f"made by {actor}",
        )
        if strength is not None:
            row.strength = strength
        if confidence is not None:
            row.confidence = confidence
        elif created_by == "user":
            row.confidence = 1.0  # a person confirming a link makes it certain
        if status is not None:
            row.status = status
        if note is not None:
            row.note = note.strip() or None
        row.updated_at = utc_now()
        self.session.flush()
        self._log(project_id, event, row, actor)
        self.session.commit()
        edge = self._edge(row)
        if builtin is not None:
            edge.origin = builtin.origin
        return edge

    def link_many(
        self,
        project_id: str,
        source: str,
        specs: Iterable[str],
        *,
        actor: str,
        created_by: str = "system",
    ) -> tuple[list[str], list[str]]:
        """Links an agent sends along with a write, each written "relationship target"
        ("caused_by DEC-002", "uses file:src/a.gd", "applies_to global:RULE-3"; a target alone
        means relates_to), all from ``source``. Returns (made, skipped with the reason). A bad
        entry is reported, never raised: the record it came with is already saved."""
        made: list[str] = []
        skipped: list[str] = []
        for spec in specs:
            text = " ".join(str(spec).split())
            if not text:
                continue
            try:
                relationship, target = self.parse_link(text)
                self.link(
                    project_id, source, relationship, target, created_by=created_by, actor=actor
                )
            except HTTPException as error:
                self.session.rollback()
                skipped.append(f"{text}: {error.detail}")
                continue
            made.append(f"{relationship} {target}")
        return made, skipped

    @staticmethod
    def parse_link(text: str) -> tuple[str, str]:
        """Split "caused_by DEC-002" into ("caused_by", "DEC-002"). Relationship names may be
        written with spaces ("depends on CAMP-3"). A target alone is relates_to."""
        words = text.split(" ")
        for cut in range(min(len(words) - 1, RELATIONSHIP_WORDS), 0, -1):
            name = "_".join(words[:cut]).rstrip(":")
            key = name.lower().replace("-", "_")
            if key in RELATIONSHIPS or key in INVERSES:
                return name, " ".join(words[cut:])
        if len(words) > 1 and ":" not in words[0]:
            raise invalid(
                f"{words[0]!r} is not a known relationship. Write each link as "
                "'relationship target', for example 'caused_by DEC-002'."
            )
        return "relates_to", text

    def _new_row(
        self,
        project_id: str,
        a: Node,
        b: Node,
        relationship: str,
        builtin: Edge | None,
        created_by: str,
        actor: str,
        *,
        status: str = "active",
        confidence: float | None = None,
    ) -> DataLink:
        row = DataLink(
            project_id=project_id,
            source_kind=a.kind,
            source_id=a.id,
            target_kind=b.kind,
            target_id=b.id,
            relationship=relationship,
            strength=builtin.strength if builtin else DEFAULT_STRENGTH,
            confidence=DEFAULT_CONFIDENCE[created_by] if confidence is None else confidence,
            created_by=created_by,
            actor=actor,
            status=status,
            contextual_weights={},
            provenance=[],
            # Set here, not left to the column defaults: those apply only when the row is
            # flushed, and reinforce() counts on a row it has just made.
            traversal_count=0,
            success_count=0,
            failure_count=0,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.session.add(row)
        return row

    @staticmethod
    def _add_provenance(row: DataLink, source: str, detail: str) -> None:
        entry = {"source": source, "detail": detail, "at": utc_now().isoformat()}
        kept = [p for p in (row.provenance or []) if p.get("detail") != detail]
        row.provenance = [*kept, entry][-PROVENANCE_KEEP:]

    def reject(self, project_id: str, link_id: str, actor: str = HUMAN) -> Edge:
        """Mark a link as wrong. It stops being traversed, and inference will not propose
        the same link again unless a person or agent asserts it."""
        row = self._row(project_id, link_id)
        row.status = "rejected"
        self._add_provenance(
            row, "correction", "rejected by a person" if actor == HUMAN else f"rejected by {actor}"
        )
        row.updated_at = utc_now()
        self._log(project_id, "LINK_REJECTED", row, actor)
        self.session.commit()
        return self._edge(row)

    def confirm(self, project_id: str, link_id: str, actor: str = HUMAN) -> Edge:
        row = self._row(project_id, link_id)
        row.status = "active"
        row.confidence = max(row.confidence, 1.0 if actor == HUMAN else 0.8)
        self._add_provenance(
            row,
            "confirmation",
            "confirmed by a person" if actor == HUMAN else f"confirmed by {actor}",
        )
        row.updated_at = utc_now()
        self._log(project_id, "LINK_CONFIRMED", row, actor)
        self.session.commit()
        return self._edge(row)

    def _row(self, project_id: str, link_id: str) -> DataLink:
        row = self.session.scalar(
            select(DataLink).where(DataLink.project_id == project_id, DataLink.id == link_id)
        )
        if row is None:
            self.projects.get(project_id)
            raise not_found("That link was not found in this project")
        return row

    # ---- learning -----------------------------------------------------------------------

    def reinforce(
        self,
        project_id: str,
        key: tuple[Node, Node, str],
        *,
        operation: str,
        delta: float,
        reason: str,
    ) -> DataLink | None:
        """Strengthen (delta > 0) or weaken a link for one kind of work.

        The contextual strength for ``operation`` moves by ``delta``; the base strength moves a
        third as far, so a link can be weak for debugging and still strong for design.
        A built-in link gets an override row the first time it learns. Rejected links and
        links a person has archived are left alone."""
        source, target, relationship = key
        row = self.session.scalar(
            select(DataLink).where(
                DataLink.project_id == project_id,
                DataLink.source_kind == source.kind,
                DataLink.source_id == source.id,
                DataLink.target_kind == target.kind,
                DataLink.target_id == target.id,
                DataLink.relationship == relationship,
            )
        )
        if row is None:
            builtin = next(
                (e for e in self._builtin_edges(project_id, {source}) if e.key == key), None
            )
            if builtin is None:
                return None  # the link is gone
            row = self._new_row(
                project_id,
                source,
                target,
                relationship,
                builtin,
                "system",
                "learning",
                confidence=1.0,
            )
        if row.status in ("rejected", "archived", "superseded"):
            return None

        def clamp(value: float) -> float:
            return round(min(STRENGTH_CEILING, max(STRENGTH_FLOOR, value)), 4)

        weights = dict(row.contextual_weights or {})
        weights[operation] = clamp(weights.get(operation, row.strength) + delta)
        row.contextual_weights = weights
        row.strength = clamp(row.strength + delta / 3)
        if delta > 0:
            row.success_count += 1
            if row.status == "candidate":
                row.status = "active"  # used successfully: no longer just a guess
                row.confidence = max(row.confidence, LEARNED_CONFIDENCE)
        else:
            row.failure_count += 1
        if row.status in ("active", "weak"):
            row.status = "weak" if row.strength < WEAK_BELOW else "active"
        row.last_reinforced_at = row.updated_at = utc_now()
        self._add_provenance(row, "learning", reason)
        self.session.flush()
        return row

    def find_link(
        self, project_id: str, source: str, relationship: str, target: str
    ) -> DataLink | None:
        stored, swap = normalize_relationship(relationship)
        a = self.resolve(project_id, source, allow_global=True)
        b = self.resolve(project_id, target, allow_global=True)
        if swap:
            a, b = b, a
        return self.session.scalar(
            select(DataLink).where(
                DataLink.project_id == project_id,
                DataLink.source_kind == a.kind,
                DataLink.source_id == a.id,
                DataLink.target_kind == b.kind,
                DataLink.target_id == b.id,
                DataLink.relationship == stored,
            )
        )

    def unlink(self, project_id: str, link_id: str, actor: str = HUMAN) -> None:
        row = self.session.scalar(
            select(DataLink).where(DataLink.project_id == project_id, DataLink.id == link_id)
        )
        if row is None:
            self.projects.get(project_id)
            raise not_found(
                "That link was not found. Built-in links (task relationships, memory links, "
                "file links) are removed where they were made."
            )
        if row.status == "candidate" or row.created_by == "inferred":
            # Deleting an inferred link would let inference propose it again; remember the no.
            self.reject(project_id, row.id, actor)
            return
        self._log(project_id, "LINK_REMOVED", row, actor)
        self.session.delete(row)
        self.session.commit()

    def _log(self, project_id: str, event: str, row: DataLink, actor: str) -> None:
        a, b = Node(row.source_kind, row.source_id), Node(row.target_kind, row.target_id)
        info = self.describe(project_id, [a, b])
        title = f"{info[a].label if a in info else a.kind} {row.relationship} " + (
            info[b].label if b in info else b.kind
        )
        known = actor.lower() if actor.lower() in {"human", "codex", "claude"} else "system"
        self.activity.record(
            project_id,
            event,
            actor_type=known,
            actor_name=None if known == actor.lower() else actor,
            entity_type="link",
            entity_id=row.id,
            metadata={"title": title},
        )

    # ---- traversal ----------------------------------------------------------------------

    def traverse(
        self,
        project_id: str,
        starts: dict[Node, float],
        *,
        max_depth: int = 2,
        max_nodes: int = 40,
        min_score: float = 0.2,
        allow: Callable[[Node, NodeInfo], bool] | None = None,
        allow_step: Callable[[Node, Edge, Node], bool] | None = None,
        operation: str | None = None,
        sample: random.Random | None = None,
    ) -> dict[Node, Path]:
        """Personalized PageRank from ``starts`` (node -> starting score, 0 to 1), by pushing.

        Each starting node holds its score as relevance still to pass on. The node holding the
        most passes it along each link, scaled by the link's strength x confidence (the
        strength learned for ``operation`` when there is one) and by ``HOP_DECAY`` for every
        hop after the first. A node reached on the way whose links weigh more than
        ``HUB_WEIGHT`` in total splits it among them; starting nodes never do. A node's score
        combines what its neighbours vouch for, over every route, as a probabilistic OR, so it
        stays under 1; relevance echoing back from a node it reached does not count. Its path
        is the single strongest route, which names the reason and is what feedback teaches.

        Pushing stops when nothing left is worth ``PUSH_EPSILON``, after ``PUSH_LIMIT`` pushes,
        or at ``max_depth`` hops along the strongest route. At most ``max_nodes`` nodes reached
        beyond the starts are returned, the best first, and only those scoring at least
        ``min_score``. Negative links are never travelled, and a node that a starting node
        keeps apart with a negative link is never reached. Records that cannot be retrieved
        (superseded, hidden...), nodes ``allow`` rejects, and steps ``allow_step`` rejects are
        not taken. With ``sample``, each link's weight is drawn from its Beta distribution
        (Thompson sampling) instead of taking its mean.
        """
        best: dict[Node, Path] = {n: Path(n, s) for n, s in starts.items()}
        # What each neighbour passed to a node, the most it ever passed. Separate neighbours
        # are separate evidence and combine as a probabilistic OR: two routes of 0.5 make 0.75,
        # one route keeps its own score, and nothing reaches 1.
        arrived: dict[Node, dict[Node, float]] = {n: {n: min(s, 1.0)} for n, s in starts.items()}
        residual: dict[Node, float] = dict(starts)
        heap: list[tuple[float, int, Node]] = []
        counter = 0
        for node, score in starts.items():
            heapq.heappush(heap, (-score, counter, node))
            counter += 1
        blocked: set[Node] = set()
        for e in self.edges(project_id, starts):
            if e.relationship in NEGATIVE and e.status in TRAVERSABLE_STATUSES:
                blocked.add(e.other(e.source if e.source in starts else e.target))
        info_cache: dict[Node, NodeInfo] = {}
        step_cache: dict[Node, list[tuple[Edge, Node, float]]] = {}
        weights: dict[tuple, float] = {}

        def weight(e: Edge) -> float:
            if e.key not in weights:
                mean = e.weight_for(operation)
                if sample is None:
                    weights[e.key] = mean
                else:
                    seen = PRIOR_OBSERVATIONS + e.success_count + e.failure_count
                    mean = min(max(mean, 0.01), 0.99)
                    weights[e.key] = sample.betavariate(mean * seen, (1 - mean) * seen)
            return weights[e.key]

        def steps(node: Node) -> list[tuple[Edge, Node, float]]:
            if node not in step_cache:
                usable = [
                    e
                    for e in self.edges(project_id, [node])
                    if e.relationship not in NEGATIVE and e.status in TRAVERSABLE_STATUSES
                ]
                unknown = {e.other(node) for e in usable} - info_cache.keys()
                info_cache.update(self.describe(project_id, unknown))
                out = []
                for e in usable:
                    nxt = e.other(node)
                    info = info_cache.get(nxt)
                    if nxt in blocked or info is None or not info.retrievable:
                        continue
                    if allow is not None and not allow(nxt, info):
                        continue
                    if allow_step is not None and not allow_step(node, e, nxt):
                        continue
                    out.append((e, nxt, weight(e)))
                step_cache[node] = out
            return step_cache[node]

        def score(node: Node) -> float:
            missed = 1.0
            for giver, amount in arrived.get(node, {}).items():
                # Relevance that came back from a node this one reached is an echo, not news.
                if giver != node and any(start == node for start, _, _ in best[giver].hops):
                    continue
                missed *= 1 - amount
            return 1 - missed

        pushes = 0
        while heap and pushes < PUSH_LIMIT:
            _, _, node = heapq.heappop(heap)
            if residual.get(node, 0.0) < PUSH_EPSILON:
                continue  # an older heap entry for a node already pushed
            mass, residual[node] = residual[node], 0.0
            pushes += 1
            path = best[node]
            if path.depth >= max_depth:
                continue
            out = steps(node)
            # A starting node passes on all it has: everything linked to the task matters. A
            # node reached on the way shares it out when its links weigh more than HUB_WEIGHT.
            share = 1 / max(1.0, sum(w for _, _, w in out) / HUB_WEIGHT) if path.hops else 1.0
            decay = HOP_DECAY if path.hops else 1.0
            now = score(node)
            for e, nxt, w in out:
                passed = mass * w * decay * share
                if passed < PUSH_EPSILON / 4:
                    continue
                route = path.score * w * decay
                if nxt not in best or route > best[nxt].score:
                    hops = [*path.hops, (path.node, e.read_from(path.node), e)]
                    best[nxt] = Path(nxt, route, hops)
                # What this neighbour vouches for: its own score, carried over the link. The
                # mass only decides what is pushed next and when to stop.
                given = arrived.setdefault(nxt, {})
                given[node] = max(given.get(node, 0.0), min(1.0, now * w * decay * share))
                residual[nxt] = residual.get(nxt, 0.0) + passed
                heapq.heappush(heap, (-residual[nxt], counter, nxt))
                counter += 1

        scores = {n: round(score(n), 6) for n in best}
        found = {n: Path(n, scores[n], p.hops) for n, p in best.items() if scores[n] >= min_score}
        walked = sorted((p for p in found.values() if p.hops), key=lambda p: -p.score)
        keep = {p.node for p in walked[:max_nodes]}
        return {n: p for n, p in found.items() if not p.hops or n in keep}

    # ---- read models --------------------------------------------------------------------

    def node_links(self, project_id: str, ref: str) -> NodeLinks:
        node = self.resolve(project_id, ref)
        found = self.neighbours(project_id, node)
        info = self.describe(project_id, [node, *(other for _, other, _ in found)])
        links = [
            LinkRead(
                id=e.link_id,
                relationship=read_as,
                stored_relationship=e.relationship,
                direction="outgoing" if e.source == node else "incoming",
                group=RELATIONSHIPS[e.relationship][1],
                node=self.node_read(info[other]),
                strength=e.strength,
                confidence=e.confidence,
                status=e.status,
                origin=e.origin,
                created_by=e.created_by,
                note=e.note,
                provenance=e.provenance,
                contextual_weights=e.contextual_weights,
                success_count=e.success_count,
                failure_count=e.failure_count,
            )
            for e, other, read_as in found
            if other in info and e.status != "rejected"
        ]
        return NodeLinks(node=self.node_read(info[node]), links=links)

    def link_read(self, project_id: str, edge: Edge) -> LinkRead:
        """A freshly written link, read from its source."""
        info = self.describe(project_id, [edge.target])
        return LinkRead(
            id=edge.link_id,
            relationship=edge.relationship,
            stored_relationship=edge.relationship,
            direction="outgoing",
            group=RELATIONSHIPS[edge.relationship][1],
            node=self.node_read(info[edge.target]),
            strength=edge.strength,
            confidence=edge.confidence,
            status=edge.status,
            origin=edge.origin,
            created_by=edge.created_by,
            note=edge.note,
            provenance=edge.provenance,
            contextual_weights=edge.contextual_weights,
            success_count=edge.success_count,
            failure_count=edge.failure_count,
        )

    @staticmethod
    def node_read(info: NodeInfo) -> NodeRead:
        return NodeRead(
            kind=info.node.kind,
            id=info.node.id,
            label=info.label,
            title=info.title,
            subtype=info.subtype,
            status=info.status,
        )

    @staticmethod
    def relationship_types() -> list[RelationshipType]:
        return [
            RelationshipType(name=name, inverse=inverse, group=group)
            for name, (inverse, group) in RELATIONSHIPS.items()
        ]

    # ---- whole-graph view ---------------------------------------------------------------

    def view_all(self, limit: int = 6000) -> dict:
        """The whole workspace as one brain: every project that isn't archived, plus the global
        rules. Each node and shelf carries its project; links never cross projects."""
        from app.models.project import GLOBAL_PROJECT_ID, Project

        projects = list(
            self.session.scalars(
                select(Project).where(Project.status != "archived").order_by(Project.name)
            )
        )
        projects.sort(key=lambda p: p.id != GLOBAL_PROJECT_ID)  # global rules first
        out: dict = {"projects": [], "nodes": [], "links": [], "shelves": []}
        for project in projects:
            room = limit - len(out["nodes"])
            if room <= 0:
                break
            part = self.view(project.id, limit=room)
            if not part["nodes"]:
                continue
            out["projects"].append(
                {
                    "id": project.id,
                    "name": "Global rules" if project.id == GLOBAL_PROJECT_ID else project.name,
                    "accent": project.accent,
                    "global": project.id == GLOBAL_PROJECT_ID,
                }
            )
            out["nodes"] += [{**n, "project_id": project.id} for n in part["nodes"]]
            out["links"] += part["links"] + part["routes"]
            # The shared tree comes once, with the Global scope; every project files on it.
            seen = {s["id"] for s in out["shelves"]}
            out["shelves"] += [
                {**s, "project_id": GLOBAL_PROJECT_ID if s["shared"] else project.id}
                for s in part["shelves"]
                if s["id"] not in seen
            ]
        return out

    def view(self, project_id: str, limit: int = 3000) -> dict:
        """Every visible record of the project and the links between them, for the Brain View.
        Titles and labels only, never content."""
        from app.models.files import ProjectFile
        from app.models.graph import Shelf
        from app.services.shelves import ShelfService

        self.projects.get(project_id)
        nodes: set[Node] = set()
        nodes |= {
            Node("memory", i)
            for i in self.session.scalars(
                select(Memory.id).where(
                    Memory.project_id == project_id,
                    Memory.status == "active",
                    Memory.ai_visibility != "hidden",
                )
            )
        }
        nodes |= {
            Node("task", i)
            for i in self.session.scalars(
                select(Task.id).where(Task.project_id == project_id, Task.status != "archived")
            )
        }
        nodes |= {
            Node("file", i)
            for i in self.session.scalars(
                select(ProjectFile.id).where(ProjectFile.project_id == project_id)
            )
        }
        nodes |= {
            Node("milestone", i)
            for i in self.session.scalars(
                select(Milestone.id).where(
                    Milestone.project_id == project_id, Milestone.status != "archived"
                )
            )
        }
        nodes = set(sorted(nodes)[:limit])
        info = self.describe(project_id, nodes)
        shelf_service = ShelfService(self.session)
        memberships = shelf_service.memberships(project_id)
        shared, shared_members = shelf_service.shared(project_id)
        memberships.update(shared_members)
        node_shelves: dict[Node, list[str]] = {}
        for shelf_id, members in memberships.items():
            for n in members:
                node_shelves.setdefault(n, []).append(shelf_id)
        edges = [
            e
            for e in self.edges(project_id, nodes)
            if e.source in info and e.target in info and e.status in ("active", "weak", "candidate")
        ]
        degree: dict[Node, int] = {}
        for e in edges:
            if e.status != "candidate":
                degree[e.source] = degree.get(e.source, 0) + 1
                degree[e.target] = degree.get(e.target, 0) + 1
        # Routes: this project's links into Global records (Link System Phase 4).
        outside = [
            e
            for e in self._stored_edges(project_id, set(info))
            if (e.source in info) != (e.target in info)
            and e.status in ("active", "weak", "candidate")
        ]
        far = self.describe(
            project_id, [e.target if e.source in info else e.source for e in outside]
        )
        routes = [e for e in outside if e.source in far or e.target in far]
        shelves = [
            *self.session.scalars(select(Shelf).where(Shelf.project_id == project_id)),
            *shared,
        ]
        return {
            "nodes": [
                {
                    "key": f"{n.kind}:{n.id}",
                    "kind": n.kind,
                    "id": n.id,
                    "label": i.label,
                    "title": i.title,
                    "subtype": i.subtype,
                    "status": i.status,
                    "shelves": sorted(node_shelves.get(n, [])),
                    "degree": degree.get(n, 0),
                }
                for n, i in sorted(info.items())
            ],
            "links": [
                {
                    "source": f"{e.source.kind}:{e.source.id}",
                    "target": f"{e.target.kind}:{e.target.id}",
                    "relationship": e.relationship,
                    "group": RELATIONSHIPS[e.relationship][1],
                    "strength": e.strength,
                    "status": e.status,
                }
                for e in edges
            ],
            "routes": [
                {
                    "source": f"{e.source.kind}:{e.source.id}",
                    "target": f"{e.target.kind}:{e.target.id}",
                    "relationship": e.relationship,
                    "group": RELATIONSHIPS[e.relationship][1],
                    "strength": e.strength,
                    "status": e.status,
                    "route": True,
                }
                for e in routes
            ],
            "shelves": [
                {
                    "id": s.id,
                    "name": s.name,
                    "parent_id": s.parent_id,
                    "keywords": [w.strip() for w in (s.keywords or "").split(",") if w.strip()],
                    "shared": s.project_id == GLOBAL_PROJECT_ID,
                }
                for s in shelves
            ],
        }

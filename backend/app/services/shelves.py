"""Specialty Shelves: knowledge domains that stay dormant until work activates them.

A shelf is an organisational view, never a container: a record sits on any number of shelves
and still exists once. A record is on a shelf when it was put there, or when it carries a tag
with the shelf's name, so existing tags work as shelf membership without moving any data.

The shared tree: Global shelves form one tree of knowledge for every project, from broad to
specific (Knowledge > Game development > Game design > Game mechanics). A project's records sit
on it directly, or through a tag with a shelf's name, and each project only ever sees its own
records and Global ones there. Projects may still keep shelves of their own.

Activation (0 to 1) comes from three signals, and the strongest one wins:
- the task text mentions the shelf's name or one of its keywords;
- the records the work starts from (the task, its memory and files) sit on the shelf;
- activation spreading out from the task along strong links reaches records on the shelf.
A parent shelf is lifted to 70% of its most active sub-shelf. Shelves under the threshold
stay dormant.
"""

from __future__ import annotations

import re

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.app_setting import AppSetting
from app.models.graph import Shelf, ShelfMember
from app.models.memory import MemoryTag
from app.models.project import GLOBAL_PROJECT_ID, utc_now
from app.models.task import Tag, TaskTag
from app.schemas.graph import (
    NodeRead,
    ShelfActivation,
    ShelfCreate,
    ShelfDetail,
    ShelfRead,
    ShelfUpdate,
)
from app.schemas.memory import HUMAN
from app.services.activity import ActivityService
from app.services.errors import conflict, invalid, not_found
from app.services.graph import GraphService, Node
from app.services.projects import ProjectService
from app.services.search import STOPWORDS
from app.services.text import name_key

ACTIVATION_THRESHOLD = 0.3
WORD_EVIDENCE = "shelf_word_evidence"  # {shelf id: {word: [retrieval ids]}}
EVIDENCE_WORDS = 40  # words remembered per shelf, the best supported kept
LEARNABLE = re.compile(r"[a-z][a-z']{3,}")
WORD = re.compile(r"[\w']+")


def stem(word: str) -> str:
    """A light stem so 'inventories', 'saving' and 'saved' meet 'inventory' and 'save'."""
    w = word.casefold().strip("'")
    for suffix, replacement in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if len(w) > len(suffix) + 2 and w.endswith(suffix):
            return w[: -len(suffix)] + replacement
    return w


def stems(text: str) -> set[str]:
    return {stem(w) for w in WORD.findall(text)}


def signal_hit(signal: str, words: set[str]) -> bool:
    """Every word of the signal appears in the text."""
    parts = [stem(w) for w in WORD.findall(signal)]
    return bool(parts) and all(p in words for p in parts)


class ShelfService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.projects = ProjectService(session)
        self.graph = GraphService(session)
        self.activity = ActivityService(session)

    def get(self, project_id: str, ref: str) -> Shelf:
        """By internal id or by name, case-insensitive. A path ("Game design > Game mechanics")
        names its last shelf."""
        ref = ref.split(">")[-1]
        shelf = self.session.scalar(
            select(Shelf).where(
                Shelf.project_id == project_id,
                (Shelf.id == ref) | (Shelf.name_key == name_key(ref.strip())),
            )
        )
        if shelf is None:
            self.projects.get(project_id)
            raise not_found(f"Shelf {ref} was not found in this project")
        return shelf

    def list(self, project_id: str) -> list[ShelfRead]:
        self.projects.get(project_id)
        shelves = self._shelves(project_id)
        members = self.memberships(project_id, shelves)
        return [self._read(s, len(members.get(s.id, ()))) for s in shelves]

    def detail(self, project_id: str, ref: str) -> ShelfDetail:
        shelf = self.get(project_id, ref)
        nodes = self.memberships(project_id, [shelf]).get(shelf.id, set())
        info = self.graph.describe(project_id, nodes)
        members = sorted(
            (
                NodeRead(
                    kind=i.node.kind,
                    id=i.node.id,
                    label=i.label,
                    title=i.title,
                    subtype=i.subtype,
                    status=i.status,
                )
                for i in info.values()
            ),
            key=lambda n: (n.kind, n.label),
        )
        return ShelfDetail(**self._read(shelf, len(members)).model_dump(), members=members)

    def create(self, project_id: str, payload: ShelfCreate, actor: str = HUMAN) -> ShelfRead:
        self.projects.get(project_id)
        key = name_key(payload.name)
        if self.session.scalar(
            select(Shelf.id).where(Shelf.project_id == project_id, Shelf.name_key == key)
        ):
            raise conflict(f"A shelf named {payload.name} already exists in this project")
        now = utc_now()
        shelf = Shelf(
            project_id=project_id,
            name=payload.name,
            name_key=key,
            description=payload.description,
            parent_id=self.get(project_id, payload.parent).id if payload.parent else None,
            keywords=",".join(payload.keywords),
            created_at=now,
            updated_at=now,
        )
        self.session.add(shelf)
        self.session.flush()
        self._log(shelf, "SHELF_CREATED", actor)
        self.session.commit()
        return self._read(shelf, 0)

    def update(
        self, project_id: str, ref: str, payload: ShelfUpdate, actor: str = HUMAN
    ) -> ShelfRead:
        shelf = self.get(project_id, ref)
        fields = payload.model_fields_set
        if "name" in fields and payload.name:
            key = name_key(payload.name)
            clash = self.session.scalar(
                select(Shelf.id).where(
                    Shelf.project_id == project_id, Shelf.name_key == key, Shelf.id != shelf.id
                )
            )
            if clash:
                raise conflict(f"A shelf named {payload.name} already exists in this project")
            shelf.name, shelf.name_key = payload.name, key
        if "description" in fields:
            shelf.description = payload.description
        if "keywords" in fields and payload.keywords is not None:
            shelf.keywords = ",".join(payload.keywords)
        if "parent" in fields:
            parent = self.get(project_id, payload.parent) if payload.parent else None
            if parent is not None and self._is_within(project_id, parent.id, shelf.id):
                raise invalid("A shelf cannot sit inside itself or one of its sub-shelves")
            shelf.parent_id = parent.id if parent else None
        shelf.updated_at = utc_now()
        self._log(shelf, "SHELF_UPDATED", actor)
        self.session.commit()
        return self._read(shelf, len(self.memberships(project_id, [shelf])[shelf.id]))

    def delete(self, project_id: str, ref: str, actor: str = HUMAN) -> None:
        """Removes the shelf and its memberships. The records themselves are untouched, and
        sub-shelves move up to the deleted shelf's parent."""
        shelf = self.get(project_id, ref)
        for child in self.session.scalars(select(Shelf).where(Shelf.parent_id == shelf.id)):
            child.parent_id = shelf.parent_id
        self._log(shelf, "SHELF_DELETED", actor)
        self.session.delete(shelf)
        self.session.commit()

    def add_member(self, project_id: str, ref: str, node_ref: str, actor: str = HUMAN) -> None:
        shelf = self.get(project_id, ref)
        node = self.graph.resolve(project_id, node_ref)
        if node.kind == "shelf":
            raise invalid("Put a shelf inside another by setting its parent")
        if self.session.get(ShelfMember, (shelf.id, node.kind, node.id)) is None:
            self.session.add(
                ShelfMember(
                    shelf_id=shelf.id,
                    node_kind=node.kind,
                    node_id=node.id,
                    project_id=project_id,
                    created_at=utc_now(),
                )
            )
            self._log(shelf, "SHELF_MEMBER_ADDED", actor)
        self.session.commit()

    def remove_member(self, project_id: str, ref: str, node_ref: str, actor: str = HUMAN) -> None:
        shelf = self.get(project_id, ref)
        node = self.graph.resolve(project_id, node_ref)
        member = self.session.get(ShelfMember, (shelf.id, node.kind, node.id))
        if member is None:
            raise not_found(
                "That record is not on this shelf directly. If it is there through a tag, "
                "remove the tag instead."
            )
        self.session.delete(member)
        self._log(shelf, "SHELF_MEMBER_REMOVED", actor)
        self.session.commit()

    # ---- membership and activation ------------------------------------------------------

    def memberships(
        self,
        project_id: str,
        shelves: list[Shelf] | None = None,
        *,
        for_project: str | None = None,
    ) -> dict[str, set[Node]]:
        """Shelf id -> nodes on it, put there directly or through a tag of the same name.

        ``for_project`` reads the shared tree (Global shelves) as that project sees it: only its
        own records and Global ones, and its own tags count too."""
        shelves = self._shelves(project_id) if shelves is None else shelves
        out: dict[str, set[Node]] = {s.id: set() for s in shelves}
        if not shelves:
            return out
        for m in self.session.scalars(
            select(ShelfMember).where(ShelfMember.shelf_id.in_(list(out)))
        ):
            out[m.shelf_id].add(Node(m.node_kind, m.node_id))
        scopes = [project_id]
        if for_project is not None and for_project != project_id:
            scopes.append(for_project)
        if len(scopes) > 1 or project_id == GLOBAL_PROJECT_ID:
            # Every project files its records on the shared tree; each sees only its own.
            visible = self._owned({n for nodes in out.values() for n in nodes}, set(scopes))
            out = {sid: nodes & visible for sid, nodes in out.items()}
        by_key = {s.name_key: s.id for s in shelves}
        tags = {
            t.id: by_key[t.name_key]
            for t in self.session.scalars(
                select(Tag).where(Tag.project_id.in_(scopes), Tag.name_key.in_(list(by_key)))
            )
        }
        if tags:
            for row in self.session.execute(
                select(TaskTag.task_id, TaskTag.tag_id).where(TaskTag.tag_id.in_(list(tags)))
            ):
                out[tags[row.tag_id]].add(Node("task", row.task_id))
            for row in self.session.execute(
                select(MemoryTag.memory_id, MemoryTag.tag_id).where(
                    MemoryTag.tag_id.in_(list(tags))
                )
            ):
                out[tags[row.tag_id]].add(Node("memory", row.memory_id))
        return out

    def activate(
        self,
        project_id: str,
        text: str,
        starts: set[Node],
        *,
        threshold: float = ACTIVATION_THRESHOLD,
        memberships: dict[str, set[Node]] | None = None,
        linked: dict[str, tuple[float, str]] | None = None,
        shelves: list[Shelf] | None = None,
    ) -> list[ShelfActivation]:
        """``linked``: shelf id -> (score, reason) from activation spreading out of the task
        along strong links (design section 20); the strongest of the three signals wins."""
        shelves = self._shelves(project_id) if shelves is None else shelves
        if not shelves:
            return []
        members = self.memberships(project_id, shelves) if memberships is None else memberships
        words = stems(text)
        scores: dict[str, tuple[float, str]] = {}
        for s in shelves:
            signals = [s.name, *self._keywords(s)]
            hits = [sig for sig in signals if signal_hit(sig, words)]
            # The shelf's own name counts double.
            strength = len(hits) + (1 if hits and hits[0] == s.name else 0)
            text_score = {0: 0.0, 1: 0.7, 2: 0.85}.get(strength, 1.0)
            on_shelf = starts & members.get(s.id, set())
            member_score = (
                min(1.0, 0.6 + 0.4 * len(on_shelf) / max(len(starts), 1)) if on_shelf else 0.0
            )
            link_score, link_reason = (linked or {}).get(s.id, (0.0, ""))
            if text_score >= max(member_score, link_score) and text_score > 0:
                scores[s.id] = (text_score, "mentions " + ", ".join(hits[:3]))
            elif member_score >= link_score and member_score > 0:
                scores[s.id] = (member_score, f"{len(on_shelf)} starting record(s) on it")
            elif link_score > 0:
                scores[s.id] = (link_score, link_reason)
            else:
                scores[s.id] = (0.0, "not mentioned")
        # A sub-shelf lifts its parent: work on Save System is architecture work too.
        by_id = {s.id: s for s in shelves}
        for s in shelves:
            score, _ = scores[s.id]
            parent = by_id.get(s.parent_id) if s.parent_id else None
            while parent is not None and score > 0:
                lifted = round(score * 0.7, 4)
                if lifted > scores[parent.id][0]:
                    scores[parent.id] = (lifted, f"through sub-shelf {s.name}")
                score = lifted
                parent = by_id.get(parent.parent_id) if parent.parent_id else None

        def chain(shelf: Shelf) -> str:
            names, seen = [shelf.name], {shelf.id}
            parent = by_id.get(shelf.parent_id) if shelf.parent_id else None
            while parent is not None and parent.id not in seen:
                names.insert(0, parent.name)
                seen.add(parent.id)
                parent = by_id.get(parent.parent_id) if parent.parent_id else None
            return " > ".join(names)

        out = [
            ShelfActivation(
                id=s.id,
                name=s.name,
                activation=round(scores[s.id][0], 2),
                active=scores[s.id][0] >= threshold,
                reason=scores[s.id][1],
                path=chain(s),
                parent_id=s.parent_id,
                scope="global" if s.project_id == GLOBAL_PROJECT_ID else "project",
            )
            for s in shelves
        ]
        return sorted(out, key=lambda a: (-a.activation, a.name))

    def ensure_path(
        self, project_id: str, path: str, *, keywords: list[str] | None = None, actor=HUMAN
    ) -> Shelf:
        """The shelf a path names ("Knowledge > Game development > Game design"), creating the
        missing shelves along it, each inside the one before. ``keywords`` go to a new last
        shelf. An existing shelf found under another parent stays where it is."""
        names = [n.strip() for n in path.split(">") if n.strip()]
        if not names:
            raise invalid("Name the shelf")
        parent: Shelf | None = None
        for index, name in enumerate(names):
            try:
                shelf = self.get(project_id, name)
            except HTTPException:
                self.create(
                    project_id,
                    ShelfCreate(
                        name=name,
                        parent=parent.id if parent else None,
                        keywords=(keywords or []) if index == len(names) - 1 else [],
                    ),
                    actor=actor,
                )
                shelf = self.get(project_id, name)
            parent = shelf
        assert parent is not None
        return parent

    def path(self, shelf: Shelf) -> str:
        """The shelf's place in its tree, "Knowledge > Game development > Game design"."""
        parents = dict(
            self.session.execute(
                select(Shelf.id, Shelf.parent_id).where(Shelf.project_id == shelf.project_id)
            ).all()
        )
        names = dict(
            self.session.execute(
                select(Shelf.id, Shelf.name).where(Shelf.project_id == shelf.project_id)
            ).all()
        )
        chain, seen, node = [], set(), shelf.id
        while node is not None and node not in seen:
            chain.insert(0, names.get(node, shelf.name))
            seen.add(node)
            node = parents.get(node)
        return " > ".join(chain)

    def shared(self, project_id: str) -> tuple[list[Shelf], dict[str, set[Node]]]:
        """The shared tree as ``project_id`` sees it: Global shelves, with that project's records
        and Global ones on them."""
        if project_id == GLOBAL_PROJECT_ID:
            return [], {}
        shelves = self._shelves(GLOBAL_PROJECT_ID)
        return shelves, self.memberships(GLOBAL_PROJECT_ID, shelves, for_project=project_id)

    def find(self, project_id: str, ref: str) -> Shelf:
        """A shelf of the project, or else of the shared tree."""
        try:
            return self.get(project_id, ref)
        except HTTPException:
            if project_id == GLOBAL_PROJECT_ID:
                raise
            return self.get(GLOBAL_PROJECT_ID, ref)

    def place(
        self, project_id: str, ref: str, node_refs: list[str], *, remove: bool = False, actor=HUMAN
    ) -> Shelf:
        """Put the project's records on a shelf (its own, or one of the shared tree), or take
        them off. The records stay in their project. A record lives on the most specific shelf,
        so filing it deeper takes it off the shelves above."""
        shelf = self.find(project_id, ref)
        above = self._ancestors(shelf)
        for node_ref in node_refs:
            node = self.graph.resolve(project_id, node_ref)
            if node.kind == "shelf":
                raise invalid("Put a shelf inside another by setting its parent")
            member = self.session.get(ShelfMember, (shelf.id, node.kind, node.id))
            if remove and member is not None:
                self.session.delete(member)
                self._log(shelf, "SHELF_MEMBER_REMOVED", actor)
            elif not remove and member is None:
                for parent in above:
                    higher = self.session.get(ShelfMember, (parent.id, node.kind, node.id))
                    if higher is not None:
                        self.session.delete(higher)
                self.session.add(
                    ShelfMember(
                        shelf_id=shelf.id,
                        node_kind=node.kind,
                        node_id=node.id,
                        project_id=shelf.project_id,
                        created_at=utc_now(),
                    )
                )
                self._log(shelf, "SHELF_MEMBER_ADDED", actor)
        self.session.commit()
        return shelf

    def suggest(self, project_id: str, text: str) -> ShelfActivation | None:
        """The most specific shelf this text belongs on, in the project or the shared tree: the
        deepest shelf it wakes, the most strongly woken among equals."""
        if not text.strip():
            return None
        woken = self.activate(project_id, text, set(), memberships={})
        if project_id != GLOBAL_PROJECT_ID:
            woken += self.activate(GLOBAL_PROJECT_ID, text, set(), memberships={})
        # Only shelves the words name themselves; a parent lifted by its sub-shelf is not one.
        named = [a for a in woken if a.active and not a.reason.startswith("through sub-shelf")]
        if not named:
            return None
        return max(named, key=lambda a: (a.path.count(">"), a.activation, a.name))

    def note_helpful(self, project_id: str, text: str, nodes: set[Node], retrieval: str) -> int:
        """Remember the words of work whose pack had useful records, on the shelves those
        records sit on. A word that keeps finding a shelf's records becomes one of its keywords
        (upkeep decides, see HealthService.organize), so the shelf wakes on how people ask."""
        words = {w for w in LEARNABLE.findall(text.casefold()) if w not in STOPWORDS}
        if not words or not nodes:
            return 0
        own = self.memberships(project_id)
        shared_shelves, shared = self.shared(project_id)
        shelves = {s.id: s for s in [*self._shelves(project_id), *shared_shelves]}
        row = self.session.get(AppSetting, WORD_EVIDENCE) or AppSetting(key=WORD_EVIDENCE)
        evidence: dict = dict(row.value or {})
        noted = 0
        for shelf_id, members in {**own, **shared}.items():
            if shelf_id not in shelves or not members & nodes:
                continue
            shelf = shelves[shelf_id]
            known = stems(" ".join([shelf.name, *self._keywords(shelf)]))
            seen = dict(evidence.get(shelf_id, {}))
            for word in words:
                if stem(word) in known:
                    continue
                ids = seen.get(word, [])
                if retrieval not in ids:
                    seen[word] = [*ids, retrieval][-10:]
                    noted += 1
            best = sorted(seen.items(), key=lambda kv: -len(kv[1]))[:EVIDENCE_WORDS]
            evidence[shelf_id] = dict(best)
        row.value = evidence
        row.updated_at = utc_now()
        self.session.add(row)
        self.session.commit()
        return noted

    def owned(self, nodes: set[Node], project_id: str) -> set[Node]:
        """The records among ``nodes`` that belong to the project itself."""
        return {n for n in self._owned(nodes, {project_id}) if n.kind != "shelf"}

    def global_nodes(self, nodes: set[Node]) -> set[Node]:
        """The nodes that are Global records."""
        return self._owned(nodes, {GLOBAL_PROJECT_ID}) - {
            n for n in nodes if n.kind not in ("memory", "task", "file", "milestone")
        }

    def _owned(self, nodes: set[Node], projects: set[str]) -> set[Node]:
        """The nodes that belong to one of ``projects``."""
        from app.models.files import ProjectFile
        from app.models.memory import Memory
        from app.models.task import Milestone, Task

        tables = {"memory": Memory, "task": Task, "file": ProjectFile, "milestone": Milestone}
        out: set[Node] = set()
        for kind, table in tables.items():
            ids = [n.id for n in nodes if n.kind == kind]
            for at in range(0, len(ids), 500):
                out |= {
                    Node(kind, i)
                    for i in self.session.scalars(
                        select(table.id).where(
                            table.id.in_(ids[at : at + 500]), table.project_id.in_(projects)
                        )
                    )
                }
        return out | {n for n in nodes if n.kind not in tables}

    # ---- internals ----------------------------------------------------------------------

    def _ancestors(self, shelf: Shelf) -> list[Shelf]:
        out, seen = [], {shelf.id}
        while shelf.parent_id and shelf.parent_id not in seen:
            shelf = self.session.get(Shelf, shelf.parent_id)
            if shelf is None:
                break
            seen.add(shelf.id)
            out.append(shelf)
        return out

    def _shelves(self, project_id: str) -> list[Shelf]:
        return list(
            self.session.scalars(
                select(Shelf).where(Shelf.project_id == project_id).order_by(Shelf.name_key)
            )
        )

    @staticmethod
    def _keywords(shelf: Shelf) -> list[str]:
        return [k for k in shelf.keywords.split(",") if k]

    def _read(self, shelf: Shelf, count: int) -> ShelfRead:
        return ShelfRead(
            id=shelf.id,
            name=shelf.name,
            description=shelf.description,
            parent_id=shelf.parent_id,
            keywords=self._keywords(shelf),
            member_count=count,
        )

    def _is_within(self, project_id: str, candidate: str, root: str) -> bool:
        """Whether ``candidate`` is ``root`` or sits somewhere below it."""
        parents = dict(
            self.session.execute(
                select(Shelf.id, Shelf.parent_id).where(Shelf.project_id == project_id)
            ).all()
        )
        seen: set[str] = set()
        node: str | None = candidate
        while node is not None and node not in seen:
            if node == root:
                return True
            seen.add(node)
            node = parents.get(node)
        return False

    def _log(self, shelf: Shelf, event: str, actor: str) -> None:
        known = actor.lower() if actor.lower() in {"human", "codex", "claude"} else "system"
        self.activity.record(
            shelf.project_id,
            event,
            actor_type=known,
            actor_name=None if known == actor.lower() else actor,
            entity_type="shelf",
            entity_id=shelf.id,
            metadata={"title": shelf.name},
        )

    def count(self, project_id: str) -> int:
        return (
            self.session.scalar(
                select(func.count()).select_from(Shelf).where(Shelf.project_id == project_id)
            )
            or 0
        )

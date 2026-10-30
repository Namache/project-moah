"""Retrieval learning: remember what context packs gave agents, and learn from how it went.

An agent's context pack is recorded as a retrieval session: which records it held and the link
path that brought each one. Feedback then moves those links:
- an agent says a record helped: every link on its path is strengthened for this kind of work;
- an agent says a record did not help: the last link on its path is weakened for this kind of
  work only, so a link can stay strong for design while fading for debugging;
- a checkpoint for the task counts as mild evidence that the pack was used.
A record the agent found useful that the pack did not hold gets a link from the task, so the
next pack finds it without searching. Two records that both helped in one pack, joined by a
candidate link nobody confirmed, confirm it: the guess was right.

Records learn too (Phase 3): each verdict is counted per record and kind of work, and a record
that keeps turning out to be noise ranks lower, even when a search hit rather than a link
brought it in. One verdict barely moves it; a habit does.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.graph import OPERATIONS, NodeUsefulness, RetrievalSession
from app.models.project import utc_now
from app.services.errors import invalid, not_found
from app.services.graph import LEARNED_CONFIDENCE, GraphService, Node

USEFUL_DELTA = 0.08
NOT_USEFUL_DELTA = -0.08
CHECKPOINT_DELTA = 0.02
CHECKPOINT_WINDOW = timedelta(hours=48)
SESSION_LIMIT = 200  # sessions kept per project; older ones are dropped
# Ranking factor for a record from its verdicts: 1.0 with none, down to 0.5 for constant noise,
# up to 1.2 for constant help. Laplace-smoothed, so one verdict moves it only a little.
USEFULNESS_MIN, USEFULNESS_MAX = 0.5, 1.2

# Words that suggest each kind of work. The first operation with a hit wins, in this order.
OPERATION_WORDS: dict[str, tuple[str, ...]] = {
    "debugging": (
        "fix",
        "bug",
        "crash",
        "broken",
        "error",
        "regression",
        "duplicat",
        "fail",
        "wrong",
        "issue",
        "glitch",
        "debug",
    ),
    "testing": ("test", "verify", "qa", "coverage", "assert"),
    "art": (
        "art",
        "sprite",
        "texture",
        "shader",
        "visual",
        "animation",
        "palette",
        "icon",
        "lighting",
        "shadow",
    ),
    "design": (
        "design",
        "ux",
        "layout",
        "balance",
        "mechanic",
        "flow",
        "mockup",
        "economy",
        "progression",
    ),
    "documentation": ("doc", "readme", "write-up", "guide", "changelog", "explain"),
    "planning": ("plan", "roadmap", "milestone", "scope", "estimate", "prioriti"),
}
WORD = re.compile(r"[a-z][a-z'-]*")


def detect_operation(text: str) -> str:
    words = WORD.findall(text.casefold())
    for operation, cues in OPERATION_WORDS.items():
        if any(w.startswith(cue) for w in words for cue in cues):
            return operation
    return "coding"


def path_keys(path) -> list[list[str]]:
    return [
        [e.source.kind, e.source.id, e.target.kind, e.target.id, e.relationship]
        for _, _, e in path.hops
    ]


class RetrievalService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.graph = GraphService(session)

    def record(
        self,
        project_id: str,
        *,
        task_id: str | None,
        operation: str,
        query: str | None,
        agent: str | None,
        items: list[dict],
        tokens: int | None = None,
    ) -> RetrievalSession:
        found = RetrievalSession(
            project_id=project_id,
            task_id=task_id,
            operation=operation,
            query=query,
            agent=agent,
            items=items,
            tokens=tokens,
            created_at=utc_now(),
        )
        self.session.add(found)
        # Links that carried a record into the pack were used.
        now = utc_now()
        for item in items:
            for key in item.get("path", []):
                row = self._stored(project_id, key)
                if row is not None:
                    row.traversal_count += 1
                    row.last_used_at = now
        self.session.flush()
        old = self.session.scalars(
            select(RetrievalSession)
            .where(RetrievalSession.project_id == project_id)
            .order_by(RetrievalSession.created_at.desc())
            .offset(SESSION_LIMIT)
        ).all()
        for stale in old:
            self.session.delete(stale)
        self.session.commit()
        return found

    def get(self, project_id: str, ref: str) -> RetrievalSession:
        """By full id or by the short id shown to agents (its first 8 characters)."""
        ref = ref.strip().lower().removeprefix("r-")
        if len(ref) < 6:
            raise invalid("Give the retrieval id from the context pack, e.g. R-1a2b3c4d")
        found = self.session.scalar(
            select(RetrievalSession).where(
                RetrievalSession.project_id == project_id, RetrievalSession.id.startswith(ref)
            )
        )
        if found is None:
            raise not_found(f"Retrieval {ref} was not found in this project")
        return found

    def feedback(
        self,
        project_id: str,
        ref: str,
        *,
        useful: list[str],
        not_useful: list[str],
        actor: str,
    ) -> dict:
        retrieval = self.get(project_id, ref)
        by_node = {(i["kind"], i["id"]): i for i in retrieval.items}
        changed = 0
        added: list[str] = []
        unknown: list[str] = []
        # Linking commits, so new links wait until the verdicts are saved.
        to_link: list[tuple[Node, str]] = []
        helped: set[Node] = {Node("task", retrieval.task_id)} if retrieval.task_id else set()
        for refs, delta in ((useful, USEFUL_DELTA), (not_useful, NOT_USEFUL_DELTA)):
            for raw in refs:
                try:
                    node = self.graph.resolve(project_id, raw, allow_global=True)
                except Exception:  # noqa: BLE001 - reported back, not raised
                    unknown.append(raw)
                    continue
                item = by_node.get((node.kind, node.id))
                verdict = "useful" if delta > 0 else "not useful"
                if delta > 0:
                    helped.add(node)
                self._count(project_id, node, retrieval.operation, delta > 0)
                if item is not None:
                    item["verdict"] = verdict
                    path = item.get("path", [])
                    # Earlier hops also led somewhere useful, so a miss blames only the last.
                    for key in path if delta > 0 else path[-1:]:
                        if self._reinforce(project_id, key, retrieval, delta, verdict, actor):
                            changed += 1
                    if not path and retrieval.task_id and node != Node("task", retrieval.task_id):
                        # A search hit or a record linked straight to the task: teach the
                        # direct link, or make one, so the next pack needs no search for it.
                        direct = self._direct_link(project_id, retrieval, node)
                        if direct is not None:
                            if self._reinforce(
                                project_id, direct, retrieval, delta, verdict, actor
                            ):
                                changed += 1
                        elif delta > 0:
                            to_link.append((node, "Matched the task and helped"))
                            added.append(raw)
                elif delta > 0 and retrieval.task_id and node != Node("task", retrieval.task_id):
                    # Found useful outside the pack: link it so the next pack finds it.
                    to_link.append((node, "Found useful for this task outside its context pack"))
                    added.append(raw)
        changed += self._confirm_together(project_id, retrieval, helped, actor)
        flag_modified(retrieval, "items")  # verdicts were written into the stored items
        retrieval.outcome = "feedback"
        task_id = retrieval.task_id
        self.session.commit()
        for node, note in to_link:
            self._link_from_task(project_id, task_id, node, note, actor)
        self._teach_shelves(project_id, retrieval, helped - {Node("task", task_id or "")})
        return {"links_changed": changed, "links_added": added, "not_found": unknown}

    def _teach_shelves(self, project_id: str, retrieval: RetrievalSession, helped: set) -> None:
        """The words of this work found useful records: their shelves note them, and learn
        the ones that keep doing so."""
        from app.models.task import Task
        from app.services.shelves import ShelfService

        task = self.session.get(Task, retrieval.task_id) if retrieval.task_id else None
        text = " ".join(filter(None, [retrieval.query, task.title if task else None]))
        try:
            ShelfService(self.session).note_helpful(project_id, text, helped, retrieval.id)
        except Exception:  # noqa: BLE001 - learning never fails the feedback itself
            self.session.rollback()
            logging.getLogger(__name__).exception("Shelf word learning failed")

    def _confirm_together(self, project_id: str, retrieval, helped: set[Node], actor: str) -> int:
        """Candidate links between records that all helped this work (the task counts) are
        reinforced, which makes them active. Candidates are never walked, so this is how a
        guess between two records proves itself."""
        if len(helped) < 2:
            return 0
        confirmed = 0
        seen: set[tuple] = set()
        for e in self.graph.edges(project_id, helped):
            if e.status != "candidate" or e.key in seen:
                continue
            seen.add(e.key)
            if e.source in helped and e.target in helped:
                key = [e.source.kind, e.source.id, e.target.kind, e.target.id, e.relationship]
                if self._reinforce(
                    project_id, key, retrieval, USEFUL_DELTA, "helped together", actor
                ):
                    confirmed += 1
        return confirmed

    def _direct_link(self, project_id: str, retrieval, node: Node) -> list[str] | None:
        """The strongest usable link between the retrieval's task and ``node``, as a path key."""
        task = Node("task", retrieval.task_id)
        edges = [
            e
            for e in self.graph.edges(project_id, [task])
            if e.other(task) == node and e.status in ("active", "weak", "candidate")
        ]
        if not edges:
            return None
        e = max(edges, key=lambda e: (e.weight, e.relationship))
        return [e.source.kind, e.source.id, e.target.kind, e.target.id, e.relationship]

    def _link_from_task(self, project_id: str, task_id: str, node: Node, note: str, actor: str):
        self.graph.link(
            project_id,
            f"task:{task_id}",
            "relates_to",
            f"{node.kind}:{node.id}",
            confidence=LEARNED_CONFIDENCE,
            note=note,
            created_by="inferred",
            actor=actor,
        )

    def on_checkpoint(self, project_id: str, task_id: str | None, actor: str) -> int:
        """A checkpoint for a task is mild evidence its latest context pack was used."""
        if task_id is None:
            return 0
        retrieval = self.session.scalar(
            select(RetrievalSession)
            .where(
                RetrievalSession.project_id == project_id,
                RetrievalSession.task_id == task_id,
                RetrievalSession.outcome.is_(None),
                RetrievalSession.created_at >= utc_now() - CHECKPOINT_WINDOW,
            )
            .order_by(RetrievalSession.created_at.desc())
        )
        if retrieval is None:
            return 0
        changed = 0
        # A hop shared by several paths still counts once.
        keys = {tuple(k) for item in retrieval.items for k in item.get("path", [])}
        for key in sorted(keys):
            if self._reinforce(
                project_id,
                list(key),
                retrieval,
                CHECKPOINT_DELTA,
                "used before a checkpoint",
                actor,
            ):
                changed += 1
        retrieval.outcome = "checkpoint"
        self.session.commit()
        return changed

    def usefulness(self, project_id: str, operation: str) -> dict[Node, float]:
        """Ranking factor per record that has verdicts for this kind of work."""
        out: dict[Node, float] = {}
        for row in self.session.scalars(
            select(NodeUsefulness).where(
                NodeUsefulness.project_id == project_id, NodeUsefulness.operation == operation
            )
        ):
            share = (row.useful + 1) / (row.useful + row.not_useful + 2)
            factor = 1 + (share - 0.5) * (1.0 if share < 0.5 else 0.4)
            factor = round(min(USEFULNESS_MAX, max(USEFULNESS_MIN, factor)), 3)
            if factor != 1:
                out[Node(row.node_kind, row.node_id)] = factor
        return out

    def _count(self, project_id: str, node: Node, operation: str, useful: bool) -> None:
        if node.kind not in ("task", "memory", "file"):
            return
        operation = operation if operation in OPERATIONS else "coding"
        row = self.session.get(NodeUsefulness, (project_id, node.kind, node.id, operation))
        if row is None:
            row = NodeUsefulness(
                project_id=project_id,
                node_kind=node.kind,
                node_id=node.id,
                operation=operation,
                useful=0,
                not_useful=0,
            )
            self.session.add(row)
        if useful:
            row.useful += 1
        else:
            row.not_useful += 1
        row.updated_at = utc_now()

    def _reinforce(
        self, project_id: str, key: list[str], retrieval, delta: float, verdict: str, actor: str
    ) -> bool:
        source_kind, source_id, target_kind, target_id, relationship = key
        operation = retrieval.operation if retrieval.operation in OPERATIONS else "coding"
        row = self.graph.reinforce(
            project_id,
            (Node(source_kind, source_id), Node(target_kind, target_id), relationship),
            operation=operation,
            delta=delta,
            reason=f"{verdict} for {operation} (retrieval R-{retrieval.id[:8]}, {actor})",
        )
        return row is not None

    def _stored(self, project_id: str, key: list[str]):
        from app.models.graph import DataLink

        source_kind, source_id, target_kind, target_id, relationship = key
        return self.session.scalar(
            select(DataLink).where(
                DataLink.project_id == project_id,
                DataLink.source_kind == source_kind,
                DataLink.source_id == source_id,
                DataLink.target_kind == target_kind,
                DataLink.target_id == target_id,
                DataLink.relationship == relationship,
            )
        )

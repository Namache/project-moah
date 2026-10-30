"""Linking new information, candidate links, and orphan detection.

When a memory or task is written, Project Moah tries to connect it at once:
- **mentions**: the text names another record (DEC-004, TRAI-12) or a file with notes. That is
  strong evidence, so the link is made active (``references``, confidence 0.7);
- **similar wording**: records whose titles share the important words become *candidate*
  links (``relates_to``, confidence 0.3 to 0.55). Candidates are never traversed until a
  person or agent confirms them, or retrieval feedback shows they help.
A pair that already has any link, or whose link was rejected, is left alone.

Orphans are active records with no links and no shelf. They are knowledge nothing can reach
except a word search.

Phase 4 adds:
- **routes**: a new project record that reads like a Global record (or a new Global record that
  reads like a project's records) gets a *candidate* link to it, held by the project. That is
  the only way Global knowledge reaches a project's packs besides the standing rules, and it
  stays a guess until someone confirms it. Another project's records are never linked.
- **missing links**, found once a day: two records that both link strongly to the same two or
  more records (and those are not hubs), two records that keep helping together in the same
  packs, and orphans run through discovery again. All of them become candidates.

Agent sessions (2026-10-18):
- **the session's task**: a record an agent writes without naming a task is linked to the task
  its session is working on (``relates_to``, confidence 0.6, active), because it was written
  during that work. The MCP server knows which task that is; see ``app.mcp.server``.
- **checkpoints**: the records a checkpoint names (what the work used and changed) are linked to
  the task the checkpoint reports on, as active ``references``; to the checkpoint itself when it
  names no task.
- "global RULE-3" or "global:RULE-3" in a project record's text names the Global record, and the
  project holds the link to it, as it holds any route.
Everything runs on this computer: SQLite full-text search and word overlap, no service.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.checkpoint import Checkpoint
from app.models.files import ProjectFile
from app.models.graph import DataLink, RetrievalSession, ShelfMember
from app.models.memory import Memory
from app.models.project import GLOBAL_PROJECT_ID, Project
from app.models.task import Task
from app.services.graph import MENTION_PATTERN, GraphService, Node
from app.services.search import STOPWORDS, SearchService
from app.services.shelves import stem

log = logging.getLogger(__name__)

MENTION_CONFIDENCE = 0.7
# A record an agent writes while its session works on a task is most likely about that task.
SESSION_CONFIDENCE = 0.6
CANDIDATE_LIMIT = 3
MIN_PATH_LENGTH = 6  # shorter file names match too much ordinary text
COMMON_SHARE = 0.06  # a word in more titles than this (RESOLVED, Design...) says nothing
SIMILAR_SHARED = 2  # titles must share at least this many meaningful words...
SIMILAR_SHARE = 0.4  # ...making up at least this share of the shorter title's words
ROUTE_LIMIT = 2  # candidate routes per record and project
ROUTE_CONFIDENCE = 0.45  # crossing into Global needs closer wording than a guess inside a project
FILLER = {"never", "always", "must", "should", "only", "every", "with", "from", "into"}
# Missing links (once a day, per project)
CLOSURE_COMMON = 2  # shared strong neighbours that suggest a direct link
CLOSURE_STRENGTH = 0.5  # how strong both links to a shared neighbour must be
HUB_DEGREE = 12  # a neighbour linked to more records than this is a hub; sharing it says little
TOGETHER_PACKS = 2  # packs in which two records both helped
MISSING_LIMIT = 10  # new candidates per project per day
ORPHAN_PASS = 30  # orphans re-checked per project per day


def in_every_pack(memory: Memory) -> bool:
    """Memory every context pack carries, whatever the task: always-visible memory, and the
    person's Global rules. Links do not change whether an agent gets it."""
    return memory.ai_visibility == "always" or (
        memory.project_id == GLOBAL_PROJECT_ID and memory.type == "rule"
    )


class DiscoveryService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.graph = GraphService(session)
        self.search = SearchService(session)
        self._common: dict[str, set[str]] = {}

    def discover(self, project_id: str, ref: str, actor: str = "system") -> dict:
        """Find links for one memory or task. Returns what was made, by kind."""
        node = self.graph.resolve(project_id, ref)
        if node.kind not in ("memory", "task"):
            return {"mentions": [], "candidates": []}
        title, text = self._text(node)
        connected = self._connected(project_id, node)
        mentions = self._mentions(project_id, node, text, connected)
        connected |= {n for n, _ in mentions}
        candidates = self._similar(project_id, node, title, connected)
        routes = self._routes(project_id, node, title, connected) if node.kind == "memory" else []
        info = self.graph.describe(project_id, [n for n, _ in mentions + candidates])
        label = self.graph.describe(project_id, [node])[node].label
        made_mentions, made_candidates = [], []
        for other, detail in mentions:
            if self._store(
                project_id,
                node,
                other,
                "references",
                "active",
                MENTION_CONFIDENCE,
                "mention",
                f"{detail} in the text of {label}",
                actor,
            ):
                made_mentions.append(info[other].label)
        for other, confidence in candidates:
            if self._store(
                project_id,
                node,
                other,
                "relates_to",
                "candidate",
                confidence,
                "similar wording",
                f"titles of {label} and {info[other].label} overlap",
                actor,
            ):
                made_candidates.append(info[other].label)
        for home, a, b, confidence, detail in routes:
            if self._store(
                home, a, b, "relates_to", "candidate", confidence, "similar wording", detail, actor
            ):
                made_candidates.append(detail.split(" reads like ")[-1])
        self.session.commit()
        return {"mentions": made_mentions, "candidates": made_candidates}

    def link_to_task(self, project_id: str, ref: str, task_id: str, actor: str) -> str | None:
        """Link a record an agent just wrote to the task its session is working on, unless the
        two are linked already. Returns the task's label when a link was made. It was written
        during that work, so it is an active link, trusted a little less than a named reference;
        feedback strengthens it, and a person can reject it."""
        node = self.graph.resolve(project_id, ref)
        task = Node("task", task_id)
        info = self.graph.describe(project_id, [node, task])
        if node == task or node not in info or task not in info:
            return None
        if task in self._connected(project_id, node):
            return None
        made = self._store(
            project_id,
            node,
            task,
            "relates_to",
            "active",
            SESSION_CONFIDENCE,
            "session",
            f"written while working on {info[task].label} in the same session",
            actor,
        )
        self.session.commit()
        return info[task].label if made else None

    def discover_checkpoint(
        self, project_id: str, checkpoint_id: str, actor: str = "system"
    ) -> list[str]:
        """A checkpoint says what the work used and changed. The records its text names (DEC-004,
        a file with notes, global RULE-3) get an active references link from the task it
        reports on, or from the checkpoint itself when it names no task. Returns their labels."""
        checkpoint = self.session.get(Checkpoint, checkpoint_id)
        if checkpoint is None or checkpoint.project_id != project_id:
            return []
        task = (
            Node("task", checkpoint.task_id)
            if checkpoint.task_id
            else Node("checkpoint", checkpoint.id)
        )
        text = "\n".join(
            part
            for part in (
                checkpoint.title,
                checkpoint.summary,
                checkpoint.completed_work,
                checkpoint.remaining_work,
                checkpoint.problems,
                checkpoint.next_steps,
            )
            if part
        )
        mentions = self._mentions(project_id, task, text, self._connected(project_id, task))
        info = self.graph.describe(project_id, [n for n, _ in mentions])
        made = []
        for other, detail in mentions:
            if other in info and self._store(
                project_id,
                task,
                other,
                "references",
                "active",
                MENTION_CONFIDENCE,
                "checkpoint",
                f"{detail} in the checkpoint \u201c{checkpoint.title[:60]}\u201d",
                actor,
            ):
                made.append(info[other].label)
        self.session.commit()
        return made

    def discover_all(self, project_id: str, limit: int = 300) -> dict:
        """Backfill: run discovery over the project's active memory and open tasks."""
        refs = [
            f"memory:{m}"
            for m in self.session.scalars(
                select(Memory.id).where(Memory.project_id == project_id, Memory.status == "active")
            )
        ] + [
            f"task:{t}"
            for t in self.session.scalars(
                select(Task.id).where(
                    Task.project_id == project_id, Task.status.not_in(("archived",))
                )
            )
        ]
        totals = {"mentions": 0, "candidates": 0, "records": 0}
        for ref in refs[:limit]:
            found = self.discover(project_id, ref)
            totals["mentions"] += len(found["mentions"])
            totals["candidates"] += len(found["candidates"])
            totals["records"] += 1
        return totals

    def orphans(self, project_id: str, limit: int = 100) -> list[dict]:
        """Active memory with no link of any kind and no shelf, that only a word search can
        find. Memory every pack carries anyway (always visible, Global rules) and memory that
        comes in only when named (manual only) is left out: a link would not change how it is
        found. In the Global scope a project's route counts as a link, and an orphan is never
        found at all: packs read Global memory only through rules and routes."""
        memories = [
            m
            for m in self.session.scalars(
                select(Memory).where(
                    Memory.project_id == project_id,
                    Memory.status == "active",
                    Memory.ai_visibility.not_in(("hidden", "manual_only")),
                )
            )
            if not in_every_pack(m)
        ]
        nodes = {Node("memory", m.id) for m in memories}
        linked: set[Node] = set()
        for e in self.graph.edges(project_id, nodes):
            if e.status in ("active", "weak"):
                linked |= {e.source, e.target}
        if project_id == GLOBAL_PROJECT_ID and nodes:
            # Routes are held by the project that links to the Global record.
            ids = [n.id for n in nodes]
            for row in self.session.scalars(
                select(DataLink).where(
                    DataLink.status.in_(("active", "weak")),
                    ((DataLink.source_kind == "memory") & DataLink.source_id.in_(ids))
                    | ((DataLink.target_kind == "memory") & DataLink.target_id.in_(ids)),
                )
            ):
                linked |= {
                    Node(row.source_kind, row.source_id),
                    Node(row.target_kind, row.target_id),
                }
        shelved = {
            Node(k, i)
            for k, i in self.session.execute(
                select(ShelfMember.node_kind, ShelfMember.node_id).where(
                    ShelfMember.project_id == project_id
                )
            )
        }
        from app.services.shelves import ShelfService

        for members in ShelfService(self.session).memberships(project_id).values():
            shelved |= members
        out = [
            {"id": m.human_id, "type": m.type, "title": m.title, "node": f"memory:{m.id}"}
            for m in sorted(memories, key=lambda m: m.human_id)
            if Node("memory", m.id) not in linked and Node("memory", m.id) not in shelved
        ]
        return out[:limit]

    def candidates(self, project_id: str, limit: int = 100) -> list[dict]:
        rows = list(
            self.session.scalars(
                select(DataLink)
                .where(DataLink.project_id == project_id, DataLink.status == "candidate")
                .order_by(DataLink.confidence.desc(), DataLink.created_at)
                .limit(limit)
            )
        )
        ends = {Node(r.source_kind, r.source_id) for r in rows} | {
            Node(r.target_kind, r.target_id) for r in rows
        }
        info = self.graph.describe(project_id, ends)
        out = []
        for r in rows:
            a, b = Node(r.source_kind, r.source_id), Node(r.target_kind, r.target_id)
            if a in info and b in info:
                out.append(
                    {
                        "link_id": r.id,
                        "source": self.graph.node_read(info[a]),
                        "relationship": r.relationship,
                        "target": self.graph.node_read(info[b]),
                        "confidence": r.confidence,
                        "why": (r.provenance or [{}])[-1].get("detail", ""),
                    }
                )
        return out

    # ---- internals ----------------------------------------------------------------------

    def _text(self, node: Node) -> tuple[str, str]:
        if node.kind == "memory":
            m = self.session.get(Memory, node.id)
            return m.title, f"{m.title}\n{m.content or ''}"
        t = self.session.get(Task, node.id)
        return t.title, f"{t.title}\n{t.description or ''}\n{t.next_action or ''}"

    def _connected(self, project_id: str, node: Node) -> set[Node]:
        """Every node already tied to ``node`` by any link, rejected ones included."""
        return {e.other(node) for e in self.graph.edges(project_id, [node])}

    def _mentions(
        self, project_id: str, node: Node, text: str, connected: set[Node]
    ) -> list[tuple[Node, str]]:
        found: dict[Node, str] = {}
        named = {
            (bool(m.group("scope")), m.group("ref").upper()): None
            for m in MENTION_PATTERN.finditer(text)
        }
        for is_global, ref in named:
            try:
                if is_global and project_id != GLOBAL_PROJECT_ID:
                    other = self.graph.resolve(project_id, f"global:{ref}", allow_global=True)
                else:
                    other = self.graph.resolve(project_id, ref)
            except Exception:  # noqa: BLE001 - an ID-shaped word that names nothing
                continue
            if other != node and other not in connected:
                found.setdefault(other, f"{'global ' if is_global else ''}{ref} is named")
        lowered = text.casefold()
        for file_id, path in self.session.execute(
            select(ProjectFile.id, ProjectFile.path).where(ProjectFile.project_id == project_id)
        ):
            name = path.rsplit("/", 1)[-1]
            if len(name) < MIN_PATH_LENGTH or "." not in name:
                continue
            if re.search(rf"(?<![\w/.-]){re.escape(name.casefold())}(?![\w-])", lowered) or (
                "/" in path and path.casefold() in lowered
            ):
                other = Node("file", file_id)
                if other not in connected:
                    found.setdefault(other, f"{path} is named")
        return list(found.items())

    def _similar(
        self, project_id: str, node: Node, title: str, connected: set[Node], *, within=None
    ) -> list[tuple[Node, float]]:
        """Records in ``within`` (default: this project) whose titles share most of their
        meaningful words with ``title``. Word stems count, so "loading" meets "loads"."""
        within = within or project_id
        common = self._common_words(within) | self._common_words(project_id)
        mine = self._meaning(title, common)
        if len(mine) < SIMILAR_SHARED:
            return []
        words = sorted(mine.values(), key=len, reverse=True)[:6]
        hits = self.search.search(
            " ".join(words),
            project_id=within,
            entity_types=["memory", "task"],
            any_word=True,
            limit=25,
        )["items"]
        scored: list[tuple[float, Node]] = []
        for hit in hits:
            other = Node(hit["entity_type"], hit["entity_id"])
            if other == node or other in connected:
                continue
            if hit["entity_type"] == "memory" and hit.get("status") not in (None, "active"):
                continue
            theirs = self._meaning(hit.get("title") or "", common)
            shared = mine.keys() & theirs.keys()
            share = len(shared) / max(min(len(mine), len(theirs)), 1)
            if len(shared) >= SIMILAR_SHARED and share >= SIMILAR_SHARE:
                scored.append((share + 0.01 * len(shared), other))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [
            (other, round(min(0.55, 0.25 + 0.3 * score), 2))
            for score, other in scored[:CANDIDATE_LIMIT]
        ]

    @staticmethod
    def _meaning(title: str, common: set[str]) -> dict[str, str]:
        """Stem -> word, for the words of a title that carry meaning."""
        return {
            stem(w): w
            for w in re.findall(r"[\w']+", title.casefold())
            if len(w) > 3
            and w not in STOPWORDS
            and w not in FILLER
            and w not in common
            and not w.isdigit()
        }

    def _routes(
        self, project_id: str, node: Node, title: str, connected: set[Node]
    ) -> list[tuple[str, Node, Node, float, str]]:
        """Candidate routes between this memory and Global memory: (holding project, project
        end, global end, confidence, why). Rules are left out: they reach every pack anyway."""
        label = self.graph.describe(project_id, [node])[node].label
        out = []
        if project_id == GLOBAL_PROJECT_ID:
            homes = self.session.scalars(
                select(Project.id).where(
                    Project.id != GLOBAL_PROJECT_ID, Project.status != "archived"
                )
            ).all()
            for home in homes:
                for other, confidence in self._similar(
                    project_id, node, title, connected, within=home
                )[:ROUTE_LIMIT]:
                    if other.kind != "memory" or confidence < ROUTE_CONFIDENCE:
                        continue
                    theirs = self.graph.describe(home, [other])[other].label
                    out.append(
                        (home, other, node, confidence, f"{theirs} reads like Global {label}")
                    )
            return out
        if self.session.get(Memory, node.id).type == "rule":
            return []
        for other, confidence in self._similar(
            project_id, node, title, connected, within=GLOBAL_PROJECT_ID
        )[:ROUTE_LIMIT]:
            if other.kind != "memory" or confidence < ROUTE_CONFIDENCE:
                continue
            if self.session.get(Memory, other.id).type == "rule":
                continue
            theirs = self.graph.describe(GLOBAL_PROJECT_ID, [other])[other].label
            out.append((project_id, node, other, confidence, f"{label} reads like Global {theirs}"))
        return out

    # ---- missing links (Phase 4) --------------------------------------------------------

    def find_missing(self, project_id: str, actor: str = "system") -> dict:
        """Look for links nobody made. Everything found is a candidate for review."""
        view = self.graph.view(project_id)
        keys = {n["key"]: n for n in view["nodes"]}
        pairs = {
            tuple(sorted((link["source"], link["target"])))
            for link in self.session.execute(
                select(
                    DataLink.source_kind,
                    DataLink.source_id,
                    DataLink.target_kind,
                    DataLink.target_id,
                ).where(DataLink.project_id == project_id)
            ).all()
            for link in [{"source": f"{link[0]}:{link[1]}", "target": f"{link[2]}:{link[3]}"}]
        } | {tuple(sorted((link["source"], link["target"]))) for link in view["links"]}
        found: list[tuple[float, str, str, str]] = []  # (confidence, a, b, why)

        # Two records tied strongly to the same non-hub records probably belong together.
        strong: dict[str, set[str]] = {}
        for link in view["links"]:
            if link["status"] != "active" or link["strength"] < CLOSURE_STRENGTH:
                continue
            strong.setdefault(link["source"], set()).add(link["target"])
            strong.setdefault(link["target"], set()).add(link["source"])
        degree = {k: n["degree"] for k, n in keys.items()}
        hubs = {k for k, d in degree.items() if d > HUB_DEGREE}
        labels = {k: n["label"] for k, n in keys.items()}
        through: dict[tuple[str, str], set[str]] = {}
        for middle, ends in strong.items():
            if middle in hubs:
                continue
            ends = sorted(e for e in ends if e in keys and not e.startswith("milestone:"))
            for i, a in enumerate(ends):
                for b in ends[i + 1 :]:
                    if a.startswith("task:") and b.startswith("task:"):
                        continue  # task structure is for people to set
                    through.setdefault((a, b), set()).add(middle)
        for (a, b), middles in through.items():
            if len(middles) >= CLOSURE_COMMON and (a, b) not in pairs:
                names = " and ".join(labels[m] for m in sorted(middles)[:3])
                confidence = round(min(0.55, 0.3 + 0.05 * len(middles)), 2)
                found.append((confidence, a, b, f"both strongly linked to {names}"))

        # Records that keep helping together in the same packs.
        together: dict[tuple[str, str], int] = {}
        for r in self.session.scalars(
            select(RetrievalSession).where(
                RetrievalSession.project_id == project_id, RetrievalSession.outcome == "feedback"
            )
        ):
            helped = sorted(
                {
                    f"{i['kind']}:{i['id']}"
                    for i in r.items
                    if i.get("verdict") == "useful" and f"{i['kind']}:{i['id']}" in keys
                }
            )
            for i, a in enumerate(helped):
                for b in helped[i + 1 :]:
                    together[(a, b)] = together.get((a, b), 0) + 1
        for (a, b), n in together.items():
            if n >= TOGETHER_PACKS and (a, b) not in pairs:
                found.append((0.5, a, b, f"helped together in {n} context packs"))

        made = 0
        seen: set[tuple[str, str]] = set()
        for confidence, a, b, why in sorted(found, key=lambda f: (-f[0], f[1], f[2])):
            if made >= MISSING_LIMIT or (a, b) in seen:
                continue
            seen.add((a, b))
            na, nb = (Node(*k.split(":", 1)) for k in (a, b))
            self._store(
                project_id,
                na,
                nb,
                "relates_to",
                "candidate",
                confidence,
                "missing link",
                why,
                actor,
            )
            made += 1
        self.session.commit()
        orphans = 0
        for orphan in self.orphans(project_id, limit=ORPHAN_PASS):
            if self.discover(project_id, orphan["node"], actor)["candidates"]:
                orphans += 1
        return {"missing": made, "orphans_connected": orphans}

    def _common_words(self, project_id: str) -> set[str]:
        """Words in so many of the project's titles that sharing them says nothing."""
        if project_id not in self._common:
            titles = list(
                self.session.scalars(select(Memory.title).where(Memory.project_id == project_id))
            ) + list(self.session.scalars(select(Task.title).where(Task.project_id == project_id)))
            counts: dict[str, int] = {}
            for title in titles:
                for w in set(re.findall(r"[\w']+", title.casefold())):
                    counts[w] = counts.get(w, 0) + 1
            limit = max(4, COMMON_SHARE * len(titles))
            self._common[project_id] = {w for w, n in counts.items() if n > limit}
        return self._common[project_id]

    def _store(
        self,
        project_id: str,
        a: Node,
        b: Node,
        relationship: str,
        status: str,
        confidence: float,
        source: str,
        detail: str,
        actor: str,
    ) -> bool:
        if self._paired(a, b):
            return False  # any link between them, in any project, rejected ones included
        row = self.graph._new_row(
            project_id,
            a,
            b,
            relationship,
            None,
            "inferred",
            actor,
            status=status,
            confidence=confidence,
        )
        self.graph._add_provenance(row, source, detail)
        self.session.flush()
        return True

    def _paired(self, a: Node, b: Node) -> bool:
        def ends(x: Node, y: Node):
            return (
                (DataLink.source_kind == x.kind)
                & (DataLink.source_id == x.id)
                & (DataLink.target_kind == y.kind)
                & (DataLink.target_id == y.id)
            )

        return (
            self.session.scalar(select(DataLink.id).where(ends(a, b) | ends(b, a)).limit(1))
            is not None
        )


def discover_quietly(session: Session, project_id: str, ref: str, actor: str = "system") -> dict:
    """Discovery after a write. It must never fail the write itself, which is already saved."""
    try:
        return DiscoveryService(session).discover(project_id, ref, actor)
    except Exception:  # noqa: BLE001 - logged; the record stays saved without new links
        session.rollback()
        log.exception("Link discovery failed for %s", ref)
        return {"mentions": [], "candidates": []}


def link_to_task_quietly(
    session: Session, project_id: str, ref: str, task_id: str, actor: str = "system"
) -> str | None:
    """The session's task link after a write; like discovery, it never fails the write."""
    try:
        return DiscoveryService(session).link_to_task(project_id, ref, task_id, actor)
    except Exception:  # noqa: BLE001 - logged; the record stays saved without the link
        session.rollback()
        log.exception("Linking %s to the session's task failed", ref)
        return None


def discover_checkpoint_quietly(
    session: Session, project_id: str, checkpoint_id: str, actor: str = "system"
) -> list[str]:
    """Checkpoint links after a checkpoint is saved; they never fail the checkpoint."""
    try:
        return DiscoveryService(session).discover_checkpoint(project_id, checkpoint_id, actor)
    except Exception:  # noqa: BLE001 - logged; the checkpoint stays saved
        session.rollback()
        log.exception("Link discovery failed for checkpoint %s", checkpoint_id)
        return []

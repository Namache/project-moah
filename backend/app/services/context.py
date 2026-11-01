"""Context Pack engine: a small, ranked, budgeted summary of project truth for one task.

Safety rules, applied before anything is ranked (all enforced here, not in the UI):
- Everything is read through one ``project_id``. Another project's records cannot appear.
- Memory that is hidden, archived, invalidated, or superseded is never included.
- ``manual_only`` memory appears only when the caller names it in ``include``.
- ``relevant_only`` memory appears only when it relates to the task or the query.
- Ideas are included only when tied to the task (linked, named, every word matching, or over
  verified links), and are labelled as not requirements.

Matching, strongest first: records linked to the task; records linked to a task the request
names by ID ("check AUDIO-1", which also finds AUDIO-001) or named themselves; records reached
over verified links (a guessed link counts ``GUESS_FACTOR`` as much); then word matches. Any-word
search only proposes word matches: a record must cover ``MIN_COVERAGE`` of the meaningful words
of the task title or of the request, so one shared common word is not a match. A request asking
what was decided puts decisions and rules first.

Link System: the task, its linked records and search hits are starting nodes. Specialty
Shelves the work mentions, or that the starting nodes sit on, wake up; members of awake shelves
join the starting nodes, and members of awake Global shelves join as Global knowledge. Relevance
then spreads out over the links (Personalized PageRank, by pushing; see GraphService.traverse),
adding up over every route, so the work touches only what is near the starting nodes. Agents'
packs sample each link's weight (Thompson sampling) so untried links get a chance. A record
reached this way joins the pack with its strongest route as its reason. Records are read
through the search index, the walk and their links, never by reading the whole project. A
record that sits only on dormant shelves is left out unless it is linked to the task, named,
pinned, or always visible. Projects without shelves behave as before, with links widening what
is found.

Budget rule: items are ranked into priority tiers (0 is essential). Essential task
information is always kept, even over budget. Other items are kept in tier order; within a tier
the pack takes the set of items with the highest total score that fits (an exact knapsack), so
one long item cannot push out two short ones worth more. A memory record that repeats a
higher-ranked one in its section is left out. When an item of one tier is left out, no item
from a later tier is kept. An item is
either included whole or left out; it is never cut off partway. Tokens are counted locally for
the asking agent's provider (services/tokens.py: fitted to OpenAI's tokenizer, an estimate for
Claude's); what an agent really used is read from its own logs (services/usage.py).
"""

from __future__ import annotations

import math
import os
import random
import re
from collections import Counter, OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.app_setting import AppSetting
from app.models.project import GLOBAL_PROJECT_ID, utc_now
from app.schemas.context import (
    ContextItem,
    ContextPack,
    ContextSection,
    DetailLevel,
    ExcludedItem,
)
from app.schemas.graph import ShelfActivation
from app.schemas.memory import MemoryRead
from app.schemas.task import TaskDetail
from app.services.activity import ActivityService
from app.services.checkpoints import CheckpointService
from app.services.errors import invalid
from app.services.files import FileService
from app.services.graph import GraphService, Node, Path
from app.services.memory import MemoryService
from app.services.projects import ProjectService
from app.services.search import SearchService
from app.services.shelves import ShelfService
from app.services.tasks import CLOSED_STATUSES, TaskService
from app.services.tokens import base_tokens, count_tokens, factor

DEFAULT_BUDGETS: dict[str, int] = {"minimal": 750, "balanced": 1500, "detailed": 3000}
IMPORTANCE_SCORE = {"critical": 20, "high": 12, "normal": 5, "low": 0}
GOAL_LIMIT = 600
# Traversal budget for one pack.
GRAPH_DEPTH = 4  # hop decay and the minimum score keep long chains rare
GRAPH_NODES = 40
# Candidate records are read by id, this many per query (SQLite caps query parameters).
CANDIDATE_CHUNK = 500
# Pinned, locked and always-visible records join every pack's candidates, at most this many of
# each, the most important first.
STANDING_LIMIT = 200
# Two records in one section sharing this share of their words say the same thing.
REPEAT_OVERLAP = 0.7
GRAPH_MIN_SCORE = 0.2
# Kinds the walk may pass through. Checkpoints and shelves are reached in other ways.
GRAPH_KINDS = ("task", "memory", "file", "milestone")
# Only the best search hits start the walk; the rest are too loose a match to follow.
GRAPH_SEARCH_SEEDS = 15
EXCLUDED_SHOWN = 5
# Word matching (any-word search finds candidates; these decide which really match).
# A record must cover this share of the work's meaningful words (title words count fully, body
# words partly), so one shared common word ("old", "save") is not a match.
MIN_COVERAGE = 0.4
BODY_WEIGHT = 0.6
# An idea, or a non-decision when the request asks what was decided, needs every word.
FULL_COVERAGE = 0.99
# Chat filler that says nothing about which records matter.
FILLER = frozenset(
    "about again also any can could did does done just know let lets look need now please"
    " should show still tell think want would".split()
)
# Words that ask what was decided: decisions and rules rank first.
DECISION_WORDS = frozenset(
    "agreed choice chose chosen decide decided decision decisions settle settled".split()
)
DECISION_BOOST = 1.25
# Record IDs typed in a request ("check AUDIO-1"): an exact match beats any word match.
REF_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z0-9]*-\d+\b")
# A record reached over a link nobody verified (a guess, or a weak inferred link) counts this
# much of one reached over verified links (made or confirmed by a person, or built in).
VERIFIED_CONFIDENCE = 0.8
GUESS_FACTOR = 0.6
# Explicit rules outrank other guidance reached through links.
RULE_MULTIPLIER = 1.5
# Activation spreading from the task wakes a shelf when it reaches one of its records with at
# least this score (two strong hops do; ordinary ones fade out first).
LINK_WAKE_MIN = 0.45
LINK_WAKE_SHARE = 0.9
# Context-path cache: graph walks kept in memory, keyed by the graph version, so any change to
# knowledge (in this process or the MCP server) makes every cached walk stale at once.
PATH_CACHE_SIZE = 64
_PATH_CACHE: OrderedDict[tuple, GraphContext] = OrderedDict()
PATH_CACHE_STATS = {"hits": 0, "misses": 0}
# Cross-project routing (Phase 4): a Global record joins a project's pack only through a link
# the project holds (a route), and only when the path to it stays this strong. Routes are never
# followed onward, so nothing travels further than the one Global record.
ROUTE_MIN_SCORE = 0.3
# Predictive retrieval: records that helped with a similar earlier task start the walk.
PREDICT_SHARE = 0.5  # start score = this x how similar the earlier task is
PREDICT_SIMILAR = 0.3  # least similarity (shared title words, or the same milestone) that counts
PREDICT_SAME_MILESTONE = 0.6
PREDICT_SESSIONS = 200

CROWDED = 40  # an awake shelf holding this many of the project's records gets split
CROWDED_ASKED = "crowded_shelves_asked"  # {shelf id: when an agent was last asked}
CROWDED_AGAIN = timedelta(days=7)

# (section key, heading). Output order.
SECTIONS: list[tuple[str, str]] = [
    ("project", "PROJECT"),
    ("shelves", "ACTIVE SHELVES"),
    ("global", "GLOBAL RULES (APPLY TO EVERY PROJECT)"),
    ("milestone", "MILESTONE"),
    ("task", "CURRENT TASK"),
    ("status", "STATUS"),
    ("goal", "GOAL"),
    ("criteria", "ACCEPTANCE CRITERIA"),
    ("next", "NEXT ACTION"),
    ("blockers", "BLOCKERS"),
    ("decisions", "IMPORTANT DECISIONS"),
    ("rules", "PROJECT RULES"),
    ("warnings", "WARNINGS"),
    ("issues", "KNOWN ISSUES"),
    ("facts", "FACTS"),
    ("routed", "FROM THE GLOBAL BRAIN (LINKED TO THIS WORK)"),
    ("files", "RELEVANT FILES"),
    ("checkpoint", "LATEST CHECKPOINT"),
    ("dependencies", "DEPENDENCIES"),
    ("related", "RELATED TASKS"),
    ("ideas", "IDEAS UNDER CONSIDERATION (NOT REQUIREMENTS)"),
    ("notes", "NOTES"),
    ("history", "EARLIER CHECKPOINTS"),
    ("superseded", "REPLACED DECISIONS"),
    ("activity", "RECENT ACTIVITY"),
]
HEADING = dict(SECTIONS)
HEADING_TOKENS = {key: base_tokens(heading) for key, heading in SECTIONS}
SECTION_ORDER = {key: i for i, (key, _) in enumerate(SECTIONS)}
# Header sections print their text directly under the heading.
INLINE = {"project", "shelves", "milestone", "task", "status", "goal", "next"}
# Sections rendered one line per item; every other section separates items with a blank line.
LIST_SECTIONS = {
    "criteria",
    "dependencies",
    "related",
    "blockers",
    "files",
    "history",
    "superseded",
    "activity",
}

# Caps per section and detail level.
CAPS: dict[str, dict[str, int]] = {
    "decisions": {"minimal": 3, "balanced": 6, "detailed": 12},
    "rules": {"minimal": 0, "balanced": 5, "detailed": 10},
    # Minimal keeps the warnings and open bugs that match the work (see _memory_items): a short
    # pack that leaves out the one known trap is false economy.
    "warnings": {"minimal": 2, "balanced": 3, "detailed": 6},
    "issues": {"minimal": 2, "balanced": 4, "detailed": 8},
    "facts": {"minimal": 0, "balanced": 3, "detailed": 8},
    "routed": {"minimal": 0, "balanced": 3, "detailed": 6},
    "ideas": {"minimal": 0, "balanced": 2, "detailed": 5},
    "notes": {"minimal": 0, "balanced": 0, "detailed": 5},
    "related": {"minimal": 0, "balanced": 3, "detailed": 8},
    "history": {"minimal": 0, "balanced": 0, "detailed": 3},
    "superseded": {"minimal": 0, "balanced": 0, "detailed": 4},
    "activity": {"minimal": 0, "balanced": 3, "detailed": 8},
    "files": {"minimal": 3, "balanced": 6, "detailed": 12},
}


def estimate_tokens(text: str, provider: str | None = None) -> int:
    """Tokens of ``text`` for the asking agent's provider, counted locally (services/tokens)."""
    return count_tokens(text, provider)


def match_keys(text: str) -> set[str]:
    """The meaningful words of a text, lightly stemmed, for comparing work with records."""
    from app.services.search import STOPWORDS
    from app.services.shelves import WORD, stem

    keys = set()
    for word in WORD.findall(text):
        low = word.casefold().strip("'")
        if low in STOPWORDS or low in FILLER or low.isdigit() or REF_PATTERN.fullmatch(word):
            continue
        key = stem(low)
        keys.add(key[:-1] if len(key) > 3 and key.endswith("e") else key)  # save, saves: sav
    return keys


def verified(path: Path | None) -> bool:
    """Every link on the way was made or confirmed by a person, or is built in."""
    return path is not None and all(
        e.status == "active" and e.confidence >= VERIFIED_CONFIDENCE for _, _, e in path.hops
    )


def task_label(ref) -> str:
    """``CAMP-037 Title (in progress)`` for any object with human_id, title, and status."""
    return f"{ref.human_id} {ref.title} ({ref.status.replace('_', ' ')})"


def images_note(ref: str, images: list) -> str:
    """Tells the agent a record has pictures it can see; the pack itself carries no bytes."""
    if not images:
        return ""
    count = f"{len(images)} image" + ("s" if len(images) > 1 else "")
    return f"\n[{count} attached: brain_view_images {ref}]"


def first_paragraph(text: str | None, limit: int = GOAL_LIMIT) -> str:
    """Whole sentences from the first paragraph, up to ``limit`` characters."""
    if not text or not text.strip():
        return ""
    paragraph = " ".join(text.strip().split("\n\n")[0].split())
    if len(paragraph) <= limit:
        return paragraph
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    kept = sentences[0]
    for sentence in sentences[1:]:
        if len(kept) + 1 + len(sentence) > limit:
            break
        kept += " " + sentence
    return kept


@dataclass
class GraphContext:
    """What the Link System found for one pack."""

    activations: list[ShelfActivation] = field(default_factory=list)
    crowded: list[tuple[ShelfActivation, int]] = field(default_factory=list)
    paths: dict[Node, Path] = field(default_factory=dict)
    labels: dict[Node, str] = field(default_factory=dict)
    start_reasons: dict[Node, str] = field(default_factory=dict)
    dormant: set[Node] = field(default_factory=set)
    routed: set[Node] = field(default_factory=set)  # Global records reached through a route

    def reason(self, node: Node) -> str:
        path = self.paths[node]
        if not path.hops:
            return self.start_reasons.get(node, "matches the task")
        parts = [self.labels.get(path.hops[0][0], path.hops[0][0].kind)]
        for start, read_as, edge in path.hops:
            nxt = edge.other(start)
            parts += [read_as.replace("_", " "), self.labels.get(nxt, nxt.kind)]
        return "via " + " → ".join(parts)

    def score(self, node: Node) -> float:
        path = self.paths.get(node)
        return path.score if path else 0.0


@dataclass
class Item:
    section: str
    kind: str
    ref: str | None
    title: str
    text: str
    tier: int
    score: float = 0.0
    order: float = 0.0
    reason: str = ""
    confidence: float | None = None  # path score for records the Link System reached
    tokens: int = field(init=False)

    def __post_init__(self) -> None:
        self.tokens = base_tokens(self.text)  # provider-neutral; see ContextService.provider


class ContextService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.projects = ProjectService(session)
        self.tasks = TaskService(session)
        self.memory = MemoryService(session)
        self.checkpoints = CheckpointService(session)
        self.activity = ActivityService(session)
        self.search = SearchService(session)
        self.graph = GraphService(session)
        self.shelves = ShelfService(session)
        self.activations: list[ShelfActivation] = []
        self.graph_context = GraphContext()
        self.operation = "coding"
        self.usefulness: dict[Node, float] = {}
        self.excluded: list[ExcludedItem] = []
        self.provider: str | None = None  # whose tokens budgets and counts are in
        self.coverage: dict[str, float] = {}  # memory id -> share of the work's words it covers
        self.decision_intent = False
        self.named_tasks: dict[str, str] = {}  # task id -> human id, typed in the request
        self.named_memory: set[str] = set()  # memory ids typed in the request
        # Agents' packs explore: link weights are sampled (Thompson sampling), so links nobody
        # has tried yet get an occasional chance. Previews in the app stay deterministic.
        self.sample: random.Random | None = None

    def build(
        self,
        project_id: str,
        *,
        task: str | None = None,
        query: str | None = None,
        detail: DetailLevel = "balanced",
        budget: int | None = None,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        operation: str | None = None,
        record_for: str | None = None,
        global_rules: bool = True,
        explore: bool | None = None,
        provider: str | None = None,
    ) -> ContextPack:
        """``record_for`` names the agent asking; its pack is kept as a retrieval session so
        feedback can teach the links, and it explores (see ``sample``) unless ``explore=False``.
        Previews in the app are
        not recorded. ``global_rules=False`` leaves out the Global rules, for an agent whose
        session brief already gave them."""
        if explore is None:
            # PROJECT_BRAIN_EXPLORE=0 turns exploring off, for tests and side-by-side trials.
            explore = record_for is not None and os.environ.get("PROJECT_BRAIN_EXPLORE") != "0"
        if explore:
            self.sample = random.Random()
        self.provider = provider or record_for
        project, detail_task, kept, limit, over_budget, omitted, warnings = self.assemble(
            project_id,
            task=task,
            query=query,
            detail=detail,
            budget=budget,
            include=include,
            exclude=exclude,
            operation=operation,
            global_rules=global_rules,
        )
        retrieval_id = None
        text = self._render(kept, project.name)
        if record_for is not None:
            retrieval_id = self._record(
                project.id,
                detail_task,
                query,
                record_for,
                kept,
                estimate_tokens(text, self.provider),
            )
        return ContextPack(
            project_id=project.id,
            project_name=project.name,
            task=detail_task.human_id if detail_task else None,
            detail_level=detail,
            budget=limit,
            estimated_tokens=estimate_tokens(text, self.provider),
            over_budget=over_budget,
            text=text,
            sections=self._summarize(kept, self.provider),
            items=[
                ContextItem(
                    section=i.section,
                    kind=i.kind,
                    ref=i.ref,
                    title=i.title,
                    tokens=math.ceil(i.tokens * factor(self.provider)),
                    reason=i.reason,
                    confidence=None if i.confidence is None else round(i.confidence, 2),
                )
                for i in kept
            ],
            omitted={why: n for why, n in omitted.items() if n},
            warnings=warnings,
            shelves=self.activations,
            operation=self.operation,
            retrieval_id=retrieval_id,
            excluded=self.excluded,
        )

    def _crowded(self, graph: GraphContext) -> list[str]:
        """Ask the agent at work to split a crowded shelf into narrower categories, at most
        once a week per shelf: naming a category takes understanding the app does not have."""
        if not graph.crowded:
            return []
        row = self.session.get(AppSetting, CROWDED_ASKED) or AppSetting(key=CROWDED_ASKED)
        asked: dict = dict(row.value or {})
        now = utc_now()
        out = []
        for activation, count in sorted(graph.crowded, key=lambda c: -c[1]):
            last = asked.get(activation.id)
            if last and now - datetime.fromisoformat(last) < CROWDED_AGAIN:
                continue
            asked[activation.id] = now.isoformat()
            path = activation.path or activation.name
            out.append(
                f"Shelf {path} holds {count} of this project's records directly, too many to "
                "find things in. If this work is in that area, split it: file its records on "
                f'narrower categories with brain_update_shelf(shelf="{path} > <category>", '
                "shared=true, add=[IDs]) (brain_shelves(shelf=...) lists them). Records move "
                "off the broader shelf. Name categories of knowledge, never one word from a "
                "title."
            )
            break  # one at a time, so a pack stays about the work
        if out:
            row.value = asked
            row.updated_at = now
            self.session.add(row)
            self.session.commit()
        return out

    def _record(self, project_id, task, query, agent, kept, tokens) -> str:
        from app.services.retrieval import RetrievalService, path_keys
        from app.services.upkeep import decay_links

        items = []
        for i in kept:
            kind = i.kind.split(":")[0]
            if kind not in ("memory", "file", "task") or not i.ref:
                continue
            path = self.graph_context.paths.get(Node(kind, i.ref))
            items.append(
                {
                    "kind": kind,
                    "id": i.ref,
                    "label": i.title[:80],
                    "path": path_keys(path) if path else [],
                }
            )
        found = RetrievalService(self.session).record(
            project_id,
            task_id=task.id if task else None,
            operation=self.operation,
            query=query,
            agent=agent,
            items=items,
            tokens=tokens,
        )
        decay_links(self.session)  # at most once a day; agents asking for packs keep it going
        return found.id

    def assemble(
        self,
        project_id: str,
        *,
        task: str | None = None,
        query: str | None = None,
        detail: DetailLevel = "balanced",
        budget: int | None = None,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        operation: str | None = None,
        global_rules: bool = True,
    ):
        """Select and budget the items. Shared by context packs and handoffs."""
        if detail not in DEFAULT_BUDGETS:
            raise invalid("detail must be minimal, balanced, or detailed")
        if budget is not None and budget < 100:
            raise invalid("budget must be at least 100 tokens")
        project = self.projects.get(project_id)
        limit = budget or DEFAULT_BUDGETS[detail]
        include_ids = {ref.upper() for ref in include or []}
        exclude_ids = {ref.upper() for ref in exclude or []}
        omitted: Counter[str] = Counter()
        warnings: list[str] = []

        # The task: the one asked for, else the project's current focus, else none.
        task_ref = task or project.current_focus_task_id
        detail_task = self.tasks.detail(project_id, task_ref) if task_ref else None
        if task is None and detail_task is not None:
            warnings.append(
                f"No task was given, so the current focus {detail_task.human_id} was used."
            )
        if detail_task is None:
            warnings.append(
                "No task was given and no current focus is set; this is a project overview."
            )

        items: list[Item] = [
            Item("project", "project", project.id, project.name, project.name, 0, reason="project"),
        ]
        self.decision_intent = bool(
            {w.casefold() for w in re.findall(r"\w+", query or "")} & DECISION_WORDS
        )
        self._named(project_id, query, detail_task)
        related_memory = self._memory_relevance(
            project_id, detail_task.title if detail_task else None, query
        )
        from app.services.retrieval import detect_operation

        self.operation = operation or detect_operation(
            " ".join(
                filter(
                    None,
                    [
                        detail_task.title if detail_task else None,
                        detail_task.description if detail_task else None,
                        query,
                    ],
                )
            )
        )
        self.excluded = []
        from app.services.retrieval import RetrievalService

        self.usefulness = RetrievalService(self.session).usefulness(project_id, self.operation)
        graph = self._graph_context(project_id, detail_task, query, related_memory)
        self.graph_context = graph
        self.activations = graph.activations
        items += self._shelf_items(graph)
        warnings += self._crowded(graph)

        if detail_task is not None:
            items += self._task_items(project_id, detail_task, detail, omitted)
        else:
            items += self._overview_items(project_id, query, detail)
        if global_rules:
            items += self._global_items(project_id, detail)
        else:
            omitted["already in your brief"] += len(self._global_items(project_id, detail))
        items += self._memory_items(
            project_id,
            detail_task,
            related_memory,
            detail,
            include_ids,
            exclude_ids,
            omitted,
            graph,
        )
        items += self._routed_items(project_id, graph, detail)
        items += self._checkpoint_items(project_id, detail_task, detail)
        items += self._file_items(project_id, detail_task, query, detail, graph)
        if CAPS["activity"][detail]:
            items += self._activity_items(project_id, detail_task, detail)

        # Items are counted in provider-neutral tokens; the budget is in the agent's tokens.
        kept, over_budget = self._fit(
            items, math.floor(limit / factor(self.provider)), detail, omitted
        )
        kept_ids = {id(i) for i in kept}
        dropped = sorted(
            (i for i in items if id(i) not in kept_ids and i.confidence is not None),
            key=lambda i: -(i.confidence or 0),
        )
        self.excluded += [
            ExcludedItem(
                title=i.title,
                reason=f"left out for budget ({i.reason})",
                confidence=round(i.confidence or 0, 2),
            )
            for i in dropped[:EXCLUDED_SHOWN]
        ]
        self.excluded = self.excluded[: EXCLUDED_SHOWN * 2]
        return project, detail_task, kept, limit, over_budget, omitted, warnings

    # ---- task ---------------------------------------------------------------------------

    def _task_items(
        self, project_id: str, task: TaskDetail, detail: str, omitted: Counter[str]
    ) -> list[Item]:
        items: list[Item] = []
        if task.milestone:
            m = task.milestone
            items.append(
                Item("milestone", "milestone", m.id, m.name, m.name, 0, reason="task milestone")
            )
        items.append(
            Item(
                "task",
                "task",
                task.id,
                task.title,
                f"{task.human_id} — {task.title}" + images_note(task.human_id, task.images),
                0,
                reason="current task",
            )
        )
        status = task.status.replace("_", " ").title()
        items.append(
            Item(
                "status",
                "task",
                task.id,
                "Status",
                f"{status}, {task.priority} priority",
                0,
                reason="current task",
            )
        )
        goal = first_paragraph(task.description)
        if goal:
            items.append(Item("goal", "task", task.id, "Goal", goal, 0, reason="task description"))
        for index, criterion in enumerate(task.acceptance_criteria):
            mark = "✓" if criterion.is_completed else "✗"
            items.append(
                Item(
                    "criteria",
                    "criterion",
                    criterion.id,
                    criterion.description,
                    f"{mark} {criterion.description}",
                    4 if criterion.is_completed else 0,
                    order=index,
                    reason="completed criterion"
                    if criterion.is_completed
                    else "unfinished criterion",
                )
            )
        if task.next_action:
            items.append(
                Item(
                    "next",
                    "task",
                    task.id,
                    "Next action",
                    task.next_action,
                    0,
                    reason="task next action",
                )
            )

        blocked_by = [r for r in task.relationships if r.type == "depends_on"]
        open_deps = [r for r in blocked_by if r.task.status not in CLOSED_STATUSES]
        for rel in open_deps:
            items.append(
                Item(
                    "blockers",
                    "task",
                    rel.task.id,
                    rel.task.title,
                    f"Waiting on {task_label(rel.task)}",
                    1,
                    reason="open dependency",
                )
            )
        if task.status == "blocked" and not open_deps:
            items.append(
                Item(
                    "blockers",
                    "task",
                    task.id,
                    "Blocked",
                    "This task is marked blocked.",
                    1,
                    reason="task status",
                )
            )
        for rel in task.relationships:
            if rel.type in ("depends_on", "blocks", "parent", "child"):
                label = {
                    "depends_on": "Depends on",
                    "blocks": "Blocks",
                    "parent": "Part of",
                    "child": "Has subtask",
                }[rel.type]
                items.append(
                    Item(
                        "dependencies",
                        "task",
                        rel.task.id,
                        rel.task.title,
                        f"{label} {task_label(rel.task)}",
                        3 if rel.type in ("depends_on", "parent") else 4,
                        reason=f"task {rel.type}",
                    )
                )
            elif rel.type in ("related_to", "supersedes", "superseded_by"):
                items.append(
                    Item(
                        "related",
                        "task",
                        rel.task.id,
                        rel.task.title,
                        task_label(rel.task),
                        4,
                        reason=f"task {rel.type}",
                    )
                )
        return self._cap(items, ("related",), detail, omitted)

    def _overview_items(self, project_id: str, query: str | None, detail: str) -> list[Item]:
        """With no task, summarize what is in motion so an agent can choose where to start."""
        items: list[Item] = []
        summaries = [
            t
            for t in self.tasks.list(project_id)
            if t.status in ("in_progress", "blocked", "review")
        ]
        for index, t in enumerate(summaries[:8]):
            items.append(
                Item(
                    "related",
                    "task",
                    t.id,
                    t.title,
                    f"{t.human_id} {t.title} ({t.status.replace('_', ' ')}, "
                    f"{t.criteria_completed}/{t.criteria_total} done)",
                    1 if t.is_focus else 3,
                    order=index,
                    reason="active task",
                )
            )
        return items

    # ---- link system --------------------------------------------------------------------

    def shelf_activation(
        self, project_id: str, *, task: str | None = None, query: str | None = None
    ) -> list[ShelfActivation]:
        detail_task = self.tasks.detail(project_id, task) if task else None
        related = self._memory_relevance(
            project_id, detail_task.title if detail_task else None, query
        )
        return self._graph_context(project_id, detail_task, query, related).activations

    def _graph_context(
        self,
        project_id: str,
        task: TaskDetail | None,
        query: str | None,
        related_memory: dict[str, float],
    ) -> GraphContext:
        """The walk for this work, from the path cache when nothing has changed since."""
        from app.services.upkeep import graph_version

        predicted = self._predicted(project_id, task)
        key = (
            str(self.session.get_bind().url),
            graph_version(self.session),
            project_id,
            task.id if task else None,
            query,
            self.operation,
            tuple(sorted(related_memory.items())),
            tuple(sorted(self.usefulness.items())),
            tuple(sorted(predicted.items())),
        )
        if self.sample is not None:  # an exploring walk is drawn fresh every time
            return self._walk(project_id, task, query, related_memory, predicted)
        cached = _PATH_CACHE.get(key)
        if cached is not None:
            _PATH_CACHE.move_to_end(key)
            PATH_CACHE_STATS["hits"] += 1
            return cached
        PATH_CACHE_STATS["misses"] += 1
        ctx = self._walk(project_id, task, query, related_memory, predicted)
        _PATH_CACHE[key] = ctx
        while len(_PATH_CACHE) > PATH_CACHE_SIZE:
            _PATH_CACHE.popitem(last=False)
        return ctx

    def _walk(
        self,
        project_id: str,
        task: TaskDetail | None,
        query: str | None,
        related_memory: dict[str, float],
        predicted: dict[Node, tuple[float, str]] | None = None,
    ) -> GraphContext:
        """Starting nodes, shelf activation, and a bounded walk of the link graph."""
        ctx = GraphContext()
        starts: dict[Node, float] = {}
        if task is not None:
            starts[Node("task", task.id)] = 1.0
            ctx.start_reasons[Node("task", task.id)] = "current task"
        top_hits = sorted(related_memory.items(), key=lambda hit: -hit[1])[:GRAPH_SEARCH_SEEDS]
        for memory_id, rank in top_hits:
            # Search hits are fuzzy, so they start the walk weaker than the task does, but
            # strong enough that memory connected to them (strength 0.5) still comes along.
            node = Node("memory", memory_id)
            score = (0.42 + 0.38 * rank / 20) * self.usefulness.get(node, 1.0)
            starts[node] = max(starts.get(node, 0.0), min(1.0, score))
            ctx.start_reasons.setdefault(node, "matches the task")
        for node, (score, why) in (predicted or {}).items():
            score *= self.usefulness.get(node, 1.0)
            if score > starts.get(node, 0.0):
                starts[node] = score
                ctx.start_reasons[node] = why

        text = " ".join(
            filter(None, [task.title if task else None, task.description if task else None, query])
        )
        # The project's own shelves and the shared tree (Global shelves, holding this project's
        # records and Global ones) wake together, from the same signals.
        own = self.shelves.memberships(project_id)
        shared_shelves, shared = self.shelves.shared(project_id)
        memberships = {**own, **shared}
        routes: dict[Node, tuple[float, str]] = {}  # Global records woken by a shared shelf
        if memberships:
            # Records the work plainly starts from: the task and what is linked to it. Search
            # hits are left out, or a stray word match would wake its own shelf.
            anchors: set[Node] = set()
            if task is not None:
                # Guessed (candidate) links are not evidence yet, so they wake nothing.
                anchors = {Node("task", task.id)} | {
                    e.other(Node("task", task.id))
                    for e in self.graph.edges(project_id, [Node("task", task.id)])
                    if e.status in ("active", "weak")
                }
            linked = self._linked_shelves(project_id, task, memberships)
            ctx.activations = self.shelves.activate(
                project_id, text, anchors, memberships=own, linked=linked
            )
            if shared_shelves:
                ctx.activations += self.shelves.activate(
                    project_id,
                    text,
                    anchors,
                    memberships=shared,
                    linked=linked,
                    shelves=shared_shelves,
                )
            active = {a.id: a for a in ctx.activations if a.active}
            node_shelves: dict[Node, set[str]] = {}
            for shelf_id, nodes in memberships.items():
                for node in nodes:
                    node_shelves.setdefault(node, set()).add(shelf_id)
            ctx.dormant = {n for n, ids in node_shelves.items() if not ids & active.keys()}
            ctx.crowded = [
                (a, len(own_nodes))
                for a in active.values()
                if len(own_nodes := self.shelves.owned(memberships[a.id], project_id)) >= CROWDED
            ]
            foreign = (
                self.shelves.global_nodes({n for a in active for n in shared.get(a, ())})
                if project_id != GLOBAL_PROJECT_ID
                else set()
            )
            # Members of awake shelves join the walk: rules wake with the domain they govern.
            for shelf_id, activation in active.items():
                where = ("the Global " if activation.scope == "global" else "the ") + (
                    activation.path or activation.name
                )
                for node in memberships[shelf_id]:
                    score = 0.6 * activation.activation
                    if node in foreign:
                        # Global knowledge comes along, but the walk never runs through it.
                        if node.kind == "memory" and score > routes.get(node, (0.0, ""))[0]:
                            routes[node] = (score, f"on {where} shelf")
                    elif node.kind in GRAPH_KINDS and score > starts.get(node, 0.0):
                        starts[node] = score
                        ctx.start_reasons[node] = f"on {where} shelf"

        if not starts:
            self._route(ctx, routes)
            return ctx
        far: set[Node] = set()  # Global records seen on the way: reached, never walked through

        def allow(node: Node, info) -> bool:
            if info.scope == "global":
                far.add(node)
            return node.kind in GRAPH_KINDS and node not in ctx.dormant

        def allow_step(start: Node, _edge, node: Node) -> bool:
            # Another task is entered only from a task (subtask, dependency). Memory that informs
            # some other task does not make that task's whole context relevant here.
            return start not in far and (node.kind != "task" or start.kind == "task")

        paths = self.graph.traverse(
            project_id,
            starts,
            max_depth=GRAPH_DEPTH,
            max_nodes=GRAPH_NODES,
            min_score=GRAPH_MIN_SCORE,
            allow=allow,
            allow_step=allow_step,
            operation=self.operation,
            sample=self.sample,
        )
        ctx.paths = {
            n: p
            for n, p in paths.items()
            if n not in far or not p.hops or p.score >= ROUTE_MIN_SCORE
        }
        ctx.routed = far & ctx.paths.keys()
        self._route(ctx, routes)
        hop_nodes = {
            n for p in ctx.paths.values() for start, _, e in p.hops for n in (start, e.other(start))
        }
        ctx.labels = {n: i.label for n, i in self.graph.describe(project_id, hop_nodes).items()}
        return ctx

    @staticmethod
    def _route(ctx: GraphContext, routes: dict[Node, tuple[float, str]]) -> None:
        """Global records an awake shared shelf holds join the pack as routed Global knowledge:
        a UI preference on the Global UI shelf reaches UI work in any project, with no link
        from each project needed."""
        for node, (score, why) in routes.items():
            if score > ctx.score(node):
                ctx.paths[node] = Path(node, score)
                ctx.start_reasons[node] = why
                ctx.routed.add(node)

    def _predicted(self, project_id: str, task: TaskDetail | None) -> dict[Node, tuple[float, str]]:
        """Predictive retrieval: records agents said helped with similar earlier tasks (the same
        milestone, or titles sharing most of their words), as starting nodes for this one."""
        if task is None:
            return {}
        from sqlalchemy import select

        from app.models.graph import RetrievalSession
        from app.models.task import Task
        from app.services.shelves import stems

        sessions = [
            r
            for r in self.session.scalars(
                select(RetrievalSession)
                .where(
                    RetrievalSession.project_id == project_id,
                    RetrievalSession.task_id.is_not(None),
                    RetrievalSession.task_id != task.id,
                    RetrievalSession.outcome == "feedback",
                )
                .order_by(RetrievalSession.created_at.desc())
                .limit(PREDICT_SESSIONS)
            )
            if any(i.get("verdict") == "useful" for i in r.items)
        ]
        if not sessions:
            return {}
        others = {
            t.id: t
            for t in self.session.scalars(
                select(Task).where(
                    Task.project_id == project_id, Task.id.in_({r.task_id for r in sessions})
                )
            )
        }
        mine = stems(task.title.casefold())
        milestone = getattr(task, "milestone_id", None)
        out: dict[Node, tuple[float, str]] = {}
        for r in sessions:
            other = others.get(r.task_id)
            if other is None:
                continue
            theirs = stems(other.title.casefold())
            similar = len(mine & theirs) / max(len(mine | theirs), 1)
            if milestone and other.milestone_id == milestone:
                similar = max(similar, PREDICT_SAME_MILESTONE)
            if similar < PREDICT_SIMILAR:
                continue
            for i in r.items:
                if i.get("verdict") != "useful" or i.get("kind") not in ("memory", "file"):
                    continue
                node = Node(i["kind"], i["id"])
                score = round(PREDICT_SHARE * similar, 4)
                if score > out.get(node, (0.0, ""))[0]:
                    out[node] = (score, f"helped with similar task {other.human_id}")
        return out

    def _routed_items(self, project_id: str, graph: GraphContext, detail: str) -> list[Item]:
        """Global records a route brought in. Rules and always-visible records are already in
        every pack, so only the rest are added here."""
        if not graph.routed or project_id == GLOBAL_PROJECT_ID:
            return []
        ids = {n.id for n in graph.routed}
        items = []
        for m in self.memory.list(GLOBAL_PROJECT_ID, statuses=["active"], limit=500):
            if m.id not in ids or m.type == "rule" or m.ai_visibility in ("always", "hidden"):
                continue
            node = Node("memory", m.id)
            score = 20 * graph.score(node) * self.usefulness.get(node, 1.0)
            item = self._memory_item("routed", m, score, graph.reason(node), detail)
            item.tier = 3
            item.confidence = graph.score(node)
            items.append(item)
        return sorted(items, key=lambda i: -i.score)[: CAPS["routed"][detail]]

    def _linked_shelves(
        self, project_id: str, task: TaskDetail | None, memberships: dict[str, set[Node]]
    ) -> dict[str, tuple[float, str]]:
        """Activation propagation (design sections 20, 46 and 47): spread out from the task
        along strong links, ignoring shelves, and wake the shelves whose records light up."""
        if task is None:
            return {}
        origin = Node("task", task.id)
        lit = self.graph.traverse(
            project_id,
            {origin: 1.0},
            max_depth=2,
            max_nodes=GRAPH_NODES,
            min_score=LINK_WAKE_MIN,
            allow=lambda node, _info: node.kind in GRAPH_KINDS,
            allow_step=lambda start, _edge, node: node.kind != "task" or start.kind == "task",
            operation=self.operation,
        )
        best: dict[str, Path] = {}
        for shelf_id, members in memberships.items():
            for node in members:
                path = lit.get(node)
                if not (path and path.hops):
                    continue
                if shelf_id not in best or path.score > best[shelf_id].score:
                    best[shelf_id] = path
        if not best:
            return {}
        labels = self.graph.describe(project_id, [p.node for p in best.values()])
        return {
            shelf_id: (
                round(LINK_WAKE_SHARE * path.score, 4),
                "linked to the task through "
                + (labels[path.node].label if path.node in labels else path.node.kind),
            )
            for shelf_id, path in best.items()
        }

    @staticmethod
    def _shelf_items(graph: GraphContext) -> list[Item]:
        """Awake shelves as paths down the shelf tree, deepest first: a parent woken only
        through its sub-shelf shows as part of that sub-shelf's path."""
        if not graph.activations:
            return []
        awake = [a for a in graph.activations if a.active]
        parents = {a.parent_id for a in awake if a.parent_id}
        leaves = sorted((a for a in awake if a.id not in parents), key=lambda a: -a.activation)
        asleep = [a.name for a in graph.activations if not a.active and a.scope == "project"]
        text = (
            ", ".join(
                ("Global: " if a.scope == "global" else "")
                + f"{a.path or a.name} ({a.activation:.2f})"
                for a in leaves
            )
            or "none"
        )
        if asleep:
            more = f" and {len(asleep) - 6} more" if len(asleep) > 6 else ""
            text += f"\nDormant, left out: {', '.join(asleep[:6])}{more}"
        return [Item("shelves", "shelves", None, "Shelves", text, 3, reason="shelf activation")]

    # ---- memory -------------------------------------------------------------------------

    def _named(self, project_id: str, query: str | None, task: TaskDetail | None) -> None:
        """Tasks and records the request names by ID ("check AUDIO-1"). Visibility rules still
        apply to them: naming is not the person's include."""
        self.named_tasks, self.named_memory = {}, set()
        refs = {r.upper() for r in REF_PATTERN.findall(query or "")}
        if task is not None:
            refs.discard(task.human_id.upper())
        if not refs:
            return
        padded = {f"{r.rsplit('-', 1)[0]}-{int(r.rsplit('-', 1)[1]):03d}": r for r in refs}
        for row in self.memory.list(
            project_id, statuses=["active"], refs=refs | padded.keys(), limit=50
        ):
            self.named_memory.add(row.id)
            refs.discard(padded.get(row.human_id.upper(), row.human_id.upper()))
        for ref in refs:
            prefix, number = ref.rsplit("-", 1)
            for spelling in dict.fromkeys([ref, f"{prefix}-{int(number):03d}"]):
                try:  # AUDIO-1 is how people type AUDIO-001
                    found = self.tasks.get(project_id, spelling)
                except Exception:  # noqa: BLE001 - not a task here: an ordinary word then
                    continue
                self.named_tasks[found.id] = found.human_id
                break

    def _memory_relevance(self, project_id: str, *parts: str | None) -> dict[str, float]:
        """Memory ids that match the task title or the request, scored 0-20.

        Any-word search finds the candidates; a record then counts only when it covers enough
        of the meaningful words of the task title or of the request, whichever it matches
        better (``MIN_COVERAGE``; title words weigh more than body words). Mixing the two
        would dilute both. The score is mostly that coverage, with the search rank breaking
        ties."""
        self.coverage = {}
        decision = {k for w in DECISION_WORDS for k in match_keys(w)}
        texts = [REF_PATTERN.sub(" ", p) for p in parts if p and p.strip()]
        wanted_sets = [k for k in (match_keys(t) - decision for t in texts) if k]
        if not wanted_sets:
            return {}
        hits = self.search.search(
            " ".join(texts), project_id=project_id, entity_types=["memory"], any_word=True, limit=50
        )["items"]
        count = len(hits)
        out: dict[str, float] = {}
        for index, h in enumerate(hits):
            title = match_keys(h["title"] or "")
            body = match_keys(h["snippet"] or "") - title
            cover = max(
                min(1.0, (len(w & title) + BODY_WEIGHT * len(w & body)) / len(w))
                for w in wanted_sets
            )
            short = all(len(w) == 1 for w in wanted_sets)
            if not short and cover < MIN_COVERAGE:
                continue
            self.coverage[h["entity_id"]] = cover
            out[h["entity_id"]] = 20 * cover * (0.8 + 0.2 * (1 - index / max(count, 1)))
        return out

    def _global_items(self, project_id: str, detail: str) -> list[Item]:
        """The person's standing rules from the Global scope. Essential: never cut for budget."""
        if project_id == GLOBAL_PROJECT_ID:
            return []
        records = self.memory.list(GLOBAL_PROJECT_ID, statuses=["active"], limit=200)
        items = []
        for m in sorted(records, key=lambda m: m.human_id):
            if m.ai_visibility in ("hidden", "manual_only"):
                continue
            if m.type != "rule" and m.ai_visibility != "always":
                continue
            item = self._memory_item("global", m, 100, "global rule", detail)
            item.tier = 0
            items.append(item)
        return items

    def _candidates(
        self,
        project_id: str,
        task: TaskDetail | None,
        related: dict[str, float],
        graph: GraphContext,
        include_ids: set[str],
    ) -> list[MemoryRead]:
        """The records that could belong in this pack, found through the indexes instead of by
        reading every record: search hits, records the walk reached, records linked to the
        task, records named, and standing ones (pinned, locked, always visible). So no record
        is out of reach however large the project grows, and the work grows with the matches,
        not with the project."""
        found: dict[str, MemoryRead] = {}

        def add(rows: list[MemoryRead]) -> None:
            for m in rows:
                found.setdefault(m.id, m)

        reached = sorted(set(related) | {n.id for n in graph.paths if n.kind == "memory"})
        for at in range(0, len(reached), CANDIDATE_CHUNK):
            chunk = reached[at : at + CANDIDATE_CHUNK]
            add(self.memory.list(project_id, statuses=["active"], ids=chunk, limit=len(chunk)))
        if include_ids:
            add(self.memory.list(project_id, statuses=["active"], refs=include_ids, limit=500))
        if task is not None:
            add(self.memory.list(project_id, statuses=["active"], task=task.id, limit=500))
        for named in self.named_tasks:
            add(self.memory.list(project_id, statuses=["active"], task=named, limit=500))
        if self.named_memory:
            add(self.memory.list(project_id, statuses=["active"], ids=sorted(self.named_memory)))
        for standing in ({"pinned": True}, {"locked_only": True}, {"visibility": ["always"]}):
            add(self.memory.list(project_id, statuses=["active"], limit=STANDING_LIMIT, **standing))
        return list(found.values())

    def _memory_items(
        self,
        project_id: str,
        task: TaskDetail | None,
        related: dict[str, float],
        detail: str,
        include_ids: set[str],
        exclude_ids: set[str],
        omitted: Counter[str],
        graph: GraphContext | None = None,
    ) -> list[Item]:
        graph = graph or GraphContext()
        records = self._candidates(project_id, task, related, graph, include_ids)
        task_id = task.id if task else None
        candidates: dict[str, list[tuple[float, MemoryRead, str]]] = {}
        task_linked = {
            m.id for m in records if task_id is not None and any(t.id == task_id for t in m.tasks)
        }
        # Records the Link System reached through the graph or an awake shelf. A record that also
        # matches the task's words counts as reached when its best path came over links: links
        # that learned it helps must be able to lift it above its word match, and its reason
        # names them.
        connected = {
            m.id: graph.reason(Node("memory", m.id))
            for m in records
            if m.id not in task_linked
            and Node("memory", m.id) in graph.paths
            and (graph.paths[Node("memory", m.id)].hops or m.id not in related)
        }
        for m in records:
            if m.ai_visibility == "hidden":
                omitted["hidden"] += 1
                continue
            manual = m.human_id.upper() in include_ids or m.id.upper() in include_ids
            if m.human_id.upper() in exclude_ids or m.id.upper() in exclude_ids:
                omitted["excluded by you"] += 1
                continue
            if m.type == "bug" and m.is_resolved and not manual:
                omitted["resolved"] += 1
                continue
            if m.ai_visibility == "manual_only" and not manual:
                omitted["manual only"] += 1
                continue
            linked = task_id is not None and any(t.id == task_id for t in m.tasks)
            named_task = next(
                (self.named_tasks[t.id] for t in m.tasks if t.id in self.named_tasks), None
            )
            named = m.id in self.named_memory
            path = graph.paths.get(Node("memory", m.id))
            reach = 20 * graph.score(Node("memory", m.id)) if m.id in connected else 0.0
            if reach and not verified(path):
                reach *= GUESS_FACTOR
            if m.type == "rule":
                reach *= RULE_MULTIPLIER
            words = related.get(m.id, 0.0)
            if self.decision_intent and words:
                # The request asks what was decided: decisions and rules lead; anything else
                # needs every word to count as a match.
                if m.type in ("decision", "rule"):
                    words *= DECISION_BOOST
                elif self.coverage.get(m.id, 0.0) < FULL_COVERAGE:
                    words = 0.0
            matched = max(words, reach, 20.0 if named else 0.0) * self.usefulness.get(
                Node("memory", m.id), 1.0
            )
            always = m.ai_visibility == "always"
            standing = m.is_pinned or (m.is_locked and m.type in ("decision", "rule"))
            if Node("memory", m.id) in graph.dormant and not (
                manual or always or linked or standing or named or named_task
            ):
                omitted["dormant shelf"] += 1
                if matched > 0:
                    self.excluded.append(
                        ExcludedItem(
                            title=m.title,
                            reason="its shelves are dormant for this task",
                            confidence=None,
                        )
                    )
                continue
            # Eligibility: named by the caller, always visible, or related to the work.
            if not (
                manual
                or always
                or linked
                or named_task
                or matched > 0
                or (standing and task_id is None)
            ):
                omitted["not related"] += 1
                continue
            # An idea is never a requirement: it joins only when tied to the work, not on a
            # partial word match or a guessed link.
            if m.type == "idea" and not (
                manual
                or linked
                or named_task
                or named
                or self.coverage.get(m.id, 0.0) >= FULL_COVERAGE
                or (m.id in connected and verified(path))
            ):
                omitted["not related"] += 1
                continue
            score = (
                (50 if linked else 40 if named_task else 0)
                + (30 if always else 0)
                + (15 if m.is_pinned else 0)
                + (10 if m.is_locked else 0)
                + IMPORTANCE_SCORE[m.importance]
                + matched
            )
            reason = (
                "named by you"
                if manual
                else "linked to this task"
                if linked
                else f"linked to {named_task}, named in the request"
                if named_task
                else "named in the request"
                if named
                else "always visible"
                if always
                else "matches the task"
                if m.id not in connected and matched
                else connected[m.id]
                if m.id in connected
                else "pinned or locked"
            )
            section = {
                "decision": "decisions",
                "rule": "rules",
                "warning": "warnings",
                "bug": "issues",
                "fact": "facts",
                "idea": "ideas",
                "note": "notes",
            }[m.type]
            candidates.setdefault(section, []).append((score, m, reason))

        items: list[Item] = []
        for section, entries in candidates.items():
            cap = CAPS[section][detail]
            manual_entries = [e for e in entries if e[2] == "named by you"]
            ranked = sorted(entries, key=lambda e: (-e[0], e[1].human_id))
            if section == "decisions" and detail == "minimal":
                # Minimal keeps only decisions that are locked, high importance, or linked.
                strong = [
                    e
                    for e in ranked
                    if e[1].is_locked
                    or e[1].importance in ("critical", "high")
                    or e[2] == "linked to this task"
                ]
                omitted["detail level"] += len(ranked) - len(strong)
                ranked = strong
            if section in ("warnings", "issues") and detail == "minimal":
                # Minimal keeps only the ones this work reached, not every pinned one.
                matching = [e for e in ranked if e[2] != "pinned or locked"]
                omitted["detail level"] += len(ranked) - len(matching)
                ranked = matching
            chosen = ranked[:cap] if cap else []
            for entry in manual_entries:  # a person asked for these; the cap does not apply
                if entry not in chosen:
                    chosen.append(entry)
            omitted["detail level"] += len(ranked) - len([e for e in chosen if e in ranked])
            for score, m, reason in chosen:
                item = self._memory_item(section, m, score, reason, detail)
                path = graph.paths.get(Node("memory", m.id))
                if reason.endswith("named in the request") and item.tier > 1:
                    item.tier = 2  # typed by ID: as essential as what the person names
                if path is not None:
                    item.confidence = path.score
                if (
                    m.id in connected
                    and not related.get(m.id)
                    and path
                    and path.hops
                    and path.hops[0][0].id != task_id
                ):
                    # Reached through other records: useful, never ahead of essentials such as
                    # the latest checkpoint or memory linked to the task.
                    item.tier = max(item.tier, 3)
                items.append(item)
        if detail == "detailed":
            items += self._supersession_items(
                project_id, [i for i in items if i.section == "decisions"]
            )
        return items

    @staticmethod
    def _memory_item(section: str, m: MemoryRead, score: float, reason: str, detail: str) -> Item:
        body = " ".join(m.content.split()) if m.content else ""
        lock = " (locked)" if m.is_locked else ""
        text = (
            f"{m.human_id}{lock}\n{m.title}"
            + (f"\n{body}" if body and detail != "minimal" else "")
            + images_note(m.human_id, m.images)
        )
        strong = m.is_locked or m.importance == "critical"
        if reason == "named by you":
            tier = 2
        elif section == "decisions":
            tier = 1 if strong or m.importance == "high" or reason == "linked to this task" else 3
        elif section in ("rules", "warnings"):
            tier = 2 if strong else 3
        elif section == "issues":
            tier = 3
        elif section in ("facts", "ideas"):
            tier = 4
        else:
            tier = 5
        return Item(
            section,
            f"memory:{m.type}",
            m.id,
            m.title,
            text,
            tier,
            score=score,
            order=-score,
            reason=reason,
        )

    def _supersession_items(self, project_id: str, decisions: list[Item]) -> list[Item]:
        items: list[Item] = []
        for decision in decisions:
            memory = self.memory.get(project_id, decision.ref or "")
            if memory.supersedes_id:
                old = self.memory.get(project_id, memory.supersedes_id)
                items.append(
                    Item(
                        "superseded",
                        "memory:decision",
                        old.id,
                        old.title,
                        f"{memory.human_id} replaces {old.human_id}: {old.title}",
                        5,
                        order=-decision.score,
                        reason="replaced decision",
                    )
                )
        return items[: CAPS["superseded"]["detailed"]]

    # ---- checkpoints, files, activity ---------------------------------------------------

    def _checkpoint_items(
        self, project_id: str, task: TaskDetail | None, detail: str
    ) -> list[Item]:
        scope = task.human_id if task else None
        found = self.checkpoints.list(project_id, task=scope, limit=4)
        if not found and task is not None:
            found = self.checkpoints.list(project_id, limit=4)  # fall back to the project's latest
        items: list[Item] = []
        for index, cp in enumerate(found):
            lines = [cp.title]
            if cp.summary:
                lines.append(cp.summary)
            for label, value in (
                ("Completed", cp.completed_work),
                ("Remaining", cp.remaining_work),
                ("Problems", cp.problems),
                ("Next", cp.next_steps),
            ):
                if value.strip():
                    lines.append(f"{label}: {' '.join(value.split())}")
            if index == 0:
                items.append(
                    Item(
                        "checkpoint",
                        "checkpoint",
                        cp.id,
                        cp.title,
                        "\n".join(lines),
                        1,
                        reason="latest checkpoint",
                    )
                )
            elif index <= CAPS["history"][detail]:
                items.append(
                    Item(
                        "history",
                        "checkpoint",
                        cp.id,
                        cp.title,
                        f"{cp.title}: {' '.join(cp.summary.split())}".strip(": "),
                        5,
                        order=index,
                        reason="earlier checkpoint",
                    )
                )
        return items

    def _file_items(
        self,
        project_id: str,
        task: TaskDetail | None,
        query: str | None,
        detail: str,
        graph: GraphContext | None = None,
    ) -> list[Item]:
        """Files linked to the task (or to its memory), then files the graph reached; changed
        files first."""
        cap = CAPS["files"][detail]
        if task is None or not cap:
            return []
        files = FileService(self.session)
        linked = files.files_for_task(project_id, task.id, limit=cap * 2)
        if graph is not None:
            known = {record.id for record, _ in linked}
            reached = sorted(
                (p for n, p in graph.paths.items() if n.kind == "file" and n.id not in known),
                key=lambda p: -p.score,
            )
            for path in reached[: max(cap * 2 - len(linked), 0)]:
                linked.append((files.get(project_id, path.node.id), graph.reason(path.node)))
        scores = {
            n.id: p.score for n, p in (graph.paths if graph else {}).items() if n.kind == "file"
        }
        changed = files.changed_paths(project_id) if linked else set()
        items = []
        for index, (record, reason) in enumerate(linked):
            note = record.purpose or ""
            if detail == "detailed" and record.summary:
                note = f"{note} {record.summary}".strip()
            is_changed = record.path in changed
            text = (
                record.path
                + (" (changed now)" if is_changed else "")
                + (f"\n  {' '.join(note.split())}" if note else "")
            )
            items.append(
                Item(
                    "files",
                    "file",
                    record.id,
                    record.path,
                    text,
                    2 if index < 3 else 4,
                    score=10 if is_changed else 0,
                    order=-(10 if is_changed else 0) + index,
                    reason=reason + (", changed in the working tree" if is_changed else ""),
                    confidence=scores.get(record.id),
                )
            )
        return items[:cap]

    def _activity_items(self, project_id: str, task: TaskDetail | None, detail: str) -> list[Item]:
        events = self.activity.list(
            project_id=project_id,
            task=task.human_id if task else None,
            limit=CAPS["activity"][detail],
        )
        items = []
        for index, e in enumerate(events):
            who = e.actor_name or e.actor_type
            name = str(e.metadata.get("title") or e.metadata.get("name") or e.entity_type or "")
            items.append(
                Item(
                    "activity",
                    "activity",
                    e.id,
                    e.event_type,
                    f"{who}: {e.event_type.replace('_', ' ').lower()} {name}".strip(),
                    5,
                    order=index,
                    reason="recent activity",
                )
            )
        return items

    # ---- budget, rendering --------------------------------------------------------------

    @staticmethod
    def _cap(
        items: list[Item], sections: tuple[str, ...], detail: str, omitted: Counter[str]
    ) -> list[Item]:
        out: list[Item] = []
        for section in sections:
            group = [i for i in items if i.section == section]
            keep = group[: CAPS[section][detail]]
            omitted["detail level"] += len(group) - len(keep)
            out += keep
        return [i for i in items if i.section not in sections] + out

    @staticmethod
    def _fit(
        items: list[Item], limit: int, detail: str, omitted: Counter[str]
    ) -> tuple[list[Item], bool]:
        # Minimal detail leaves out finished criteria entirely; other levels rank them last.
        if detail == "minimal":
            dropped = [i for i in items if i.section == "criteria" and i.tier == 4]
            omitted["detail level"] += len(dropped)
            items = [i for i in items if i not in dropped]
        ranked = sorted(
            items, key=lambda i: (i.tier, -i.score, SECTION_ORDER[i.section], i.order, i.title)
        )
        ranked = ContextService._without_repeats(ranked, omitted)
        kept: list[Item] = []
        used = 0  # tokens, counted the way the final text is
        seen: set[str] = set()
        max_chars = limit  # in tokens; the name is kept from when budgets were characters

        def cost(item: Item) -> int:
            # An item costs its text and a separator, plus its heading the first time.
            heading = 0 if item.section in seen else HEADING_TOKENS[item.section] + 1
            return item.tokens + 1 + heading

        def keep(item: Item) -> None:
            nonlocal used
            kept.append(item)
            used += cost(item)
            seen.add(item.section)

        for item in ranked:
            if item.tier == 0:
                keep(item)  # essential, kept even over budget
        tiers = sorted({i.tier for i in ranked if i.tier > 0})
        for n, tier in enumerate(tiers):
            group = [i for i in ranked if i.tier == tier]
            # Within a tier, take the set worth the most that fits, not the first ones in line:
            # one long record must not push out two short ones that score more together.
            for item in ContextService._best_set(group, max_chars - used, cost):
                if used + cost(item) <= max_chars:
                    keep(item)
            # Top up with whatever still fits (headings shared within a section cost less
            # than the estimate assumed).
            for item in group:
                if item not in kept and used + cost(item) <= max_chars:
                    keep(item)
            left = [i for i in group if i not in kept]
            if left:
                # When an item of one tier is left out, no item from a later tier is kept.
                omitted["budget"] += len(left) + sum(1 for i in ranked if i.tier in tiers[n + 1 :])
                break
        return kept, used > max_chars

    @staticmethod
    def _best_set(group: list[Item], room: int, cost: Callable[[Item], int]) -> list[Item]:
        """The subset of ``group`` with the highest total score that fits ``room`` tokens:
        an exact 0/1 knapsack. A tier holds tens of items and the budget is a
        few thousand tokens, so this takes milliseconds. Every item is worth at least 1, so
        among equal scores the pack still takes as many as fit."""
        if room <= 0 or not group:
            return []
        weights = [cost(i) for i in group]
        capacity = room
        if sum(weights) <= capacity:
            return list(group)
        values = [max(i.score, 0.0) + 1 for i in group]
        best = [0.0] * (capacity + 1)
        took = [[False] * (capacity + 1) for _ in group]
        for k, (w, v) in enumerate(zip(weights, values, strict=True)):
            for c in range(capacity, w - 1, -1):
                if best[c - w] + v > best[c]:
                    best[c] = best[c - w] + v
                    took[k][c] = True
        chosen, c = [], capacity
        for k in range(len(group) - 1, -1, -1):
            if took[k][c]:
                chosen.append(group[k])
                c -= weights[k]
        return [i for i in group if i in chosen]

    @staticmethod
    def _without_repeats(ranked: list[Item], omitted: Counter[str]) -> list[Item]:
        """Drop a record that says nearly the same as a higher-ranked one in its section, so the
        budget is not spent twice on one point. Only memory records: tasks and files are never
        repeats of each other."""
        from app.services.shelves import stems

        out: list[Item] = []
        words: list[tuple[str, set[str]]] = []
        for item in ranked:
            if item.tier == 0 or not item.kind.startswith("memory"):
                out.append(item)
                continue
            mine = stems(f"{item.title} {item.text}")
            if len(mine) >= 4 and any(
                section == item.section and len(mine & other) / len(mine | other) >= REPEAT_OVERLAP
                for section, other in words
            ):
                omitted["repeats"] += 1
                continue
            words.append((item.section, mine))
            out.append(item)
        return out

    @staticmethod
    def _render(kept: list[Item], project_name: str) -> str:
        blocks: list[str] = []
        for key, heading in SECTIONS:
            group = sorted((i for i in kept if i.section == key), key=lambda i: (i.order, i.title))
            if not group:
                continue
            if key in INLINE or key in LIST_SECTIONS:
                blocks.append(f"{heading}\n" + "\n".join(i.text for i in group))
            else:
                blocks.append(f"{heading}\n" + "\n\n".join(i.text for i in group))
        return "\n\n".join(blocks)

    @staticmethod
    def _summarize(kept: list[Item], provider: str | None = None) -> list[ContextSection]:
        sections = []
        for key, heading in SECTIONS:
            group = [i for i in kept if i.section == key]
            if group:
                sections.append(
                    ContextSection(
                        key=key,
                        title=heading.title(),
                        tokens=math.ceil(
                            (HEADING_TOKENS[key] + 1 + sum(i.tokens + 1 for i in group))
                            * factor(provider)
                        ),
                        items=len(group),
                    )
                )
        return sections

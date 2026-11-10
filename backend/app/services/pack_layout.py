"""How a context pack is laid out: its items, the sections they go in, how many each detail
level keeps, fitting them to the token budget (the budget rule in services/context.py), and
the text an agent reads. Nothing here reads the database."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from app.schemas.context import ContextSection
from app.services.tokens import base_tokens, factor
from app.services.words import stems

# Two records in one section sharing this share of their words say the same thing.
REPEAT_OVERLAP = 0.7


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
    repeat: bool = False  # already sent to this agent session, unchanged (see SentRecords)
    tokens: int = field(init=False)

    def __post_init__(self) -> None:
        self.tokens = base_tokens(self.text)  # provider-neutral; see ContextService.provider


@dataclass
class SentRecords:
    """What one agent session has already been sent by packs in one project.

    The MCP server keeps one per project, in memory, for as long as the session lasts (see
    app.mcp.server). A repeat pack sends only what is new or changed since: an item already sent
    with the same text costs no budget and is named, not repeated. An item whose text changed
    (an edited record, a ticked criterion) counts as new.
    """

    items: dict[str, str] = field(default_factory=dict)  # item key -> fingerprint of its text
    last: str = ""  # short retrieval id of the latest pack that sent anything
    # Short retrieval ids of every pack that sent anything, oldest first: a checkpoint's
    # feedback goes to whichever of them held the records it names.
    retrievals: list[str] = field(default_factory=list)

    @staticmethod
    def key(item: Item) -> str:
        return f"{item.section}|{item.kind}|{item.ref or item.title}"

    @staticmethod
    def fingerprint(item: Item) -> str:
        import hashlib

        return hashlib.blake2b(item.text.encode(), digest_size=8).hexdigest()

    def has(self, item: Item) -> bool:
        return self.items.get(self.key(item)) == self.fingerprint(item)

    def add(self, item: Item, retrieval: str) -> None:
        self.items[self.key(item)] = self.fingerprint(item)
        self.last = retrieval or self.last
        if retrieval and retrieval not in self.retrievals:
            self.retrievals.append(retrieval)

    def resend(self) -> None:
        """Send everything again (full=true). The packs already sent still count for this
        session's feedback."""
        self.items.clear()
        self.last = ""

    def clear(self) -> None:
        self.resend()
        self.retrievals.clear()


def repeat_label(item: Item) -> str | None:
    """How a repeated item is named in a repeat pack: a record's ID, a related task's ID, a
    file's path. The pack's own task and its details (status, goal, criteria...) and activity
    are not listed: the agent knows what it is working on."""
    if item.kind.startswith("memory"):
        return item.text.split()[0] if item.text else None
    if item.section in ("related", "blockers", "dependencies") and item.kind == "task":
        first = item.text.split(" — ")[0].split()
        return first[-1] if first else None
    if item.kind == "file":
        return item.title
    return None


def cap_sections(
    items: list[Item], sections: tuple[str, ...], detail: str, omitted: Counter[str]
) -> list[Item]:
    out: list[Item] = []
    for section in sections:
        group = [i for i in items if i.section == section]
        keep = group[: CAPS[section][detail]]
        omitted["detail level"] += len(group) - len(keep)
        out += keep
    return [i for i in items if i.section not in sections] + out


def fit(
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
    ranked = without_repeats(ranked, omitted)
    kept: list[Item] = []
    used = 0  # tokens, counted the way the final text is
    seen: set[str] = set()
    max_chars = limit  # in tokens; the name is kept from when budgets were characters

    def cost(item: Item) -> int:
        # An item costs its text and a separator, plus its heading the first time. One
        # this session was already sent is only named, so it costs nothing.
        if item.repeat:
            return 0
        heading = 0 if item.section in seen else HEADING_TOKENS[item.section] + 1
        return item.tokens + 1 + heading

    def keep(item: Item) -> None:
        nonlocal used
        kept.append(item)
        used += cost(item)
        if not item.repeat:
            seen.add(item.section)

    for item in ranked:
        if item.tier == 0:
            keep(item)  # essential, kept even over budget
    tiers = sorted({i.tier for i in ranked if i.tier > 0})
    for n, tier in enumerate(tiers):
        group = [i for i in ranked if i.tier == tier]
        # Within a tier, take the set worth the most that fits, not the first ones in line:
        # one long record must not push out two short ones that score more together.
        for item in best_set(group, max_chars - used, cost):
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


def best_set(group: list[Item], room: int, cost: Callable[[Item], int]) -> list[Item]:
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


def without_repeats(ranked: list[Item], omitted: Counter[str]) -> list[Item]:
    """Drop a record that says nearly the same as a higher-ranked one in its section, so the
    budget is not spent twice on one point. Only memory records: tasks and files are never
    repeats of each other."""
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


def render(kept: list[Item], project_name: str) -> str:
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


def render_repeat(new: list[Item], repeated: list[Item], since: str | None) -> str:
    """A repeat pack: one line naming what this session already has and that still applies,
    then only what is new or changed."""
    labels = list(dict.fromkeys(filter(None, (repeat_label(i) for i in repeated))))
    ref = f" since R-{since}" if since else ""
    if not new:
        line = f"Nothing new{ref}."
        return line + (f" Still applies: {', '.join(labels)}." if labels else "")
    line = f"Already sent{ref}, unchanged, still applies: " + (
        ", ".join(labels) if labels else "the task details"
    )
    return f"{line}.\n\nNEW OR CHANGED\n\n" + render(new, "")


def summarize(kept: list[Item], provider: str | None = None) -> list[ContextSection]:
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

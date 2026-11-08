"""What an agent's checkpoint notes say about one task, for a review the agent never wrote.

Agents often write one checkpoint for a batch of tasks ("CAMP-449 …, CAMP-452 …, tests pass"),
or file a note about one task under another. Shown whole, such a note tells the person about
other work. So the lines are picked: a sentence that names other tasks of the project belongs to
them, and the sentences after it on the same line too, until a task is named again (or on the
lines under a heading such as "CAMP-449:"). A sentence that names several tasks keeps only the
part that starts at this one. In a note filed under this task, text that names no task is about
this task; in a note filed elsewhere, it is about that note's own work.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

BULLET = re.compile(r"^\s*(?:[-*•+]|\d+[.)])\s+")
TASK_REF = re.compile(r"\b([A-Z][A-Z0-9]{1,15})-(\d+)\b")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=\S)")
# What is left around a ref when only it is cut out: punctuation and a leading "and".
LEADING = re.compile(r"^(?:[\s:;,.)\]–—-]+|and\s+|plus\s+(?:an?\s+)?)", re.IGNORECASE)
TRAILING = re.compile(r"[\s:;,.(\[–—-]+$")
MIXED = "mixed"


def lines(text: str | None) -> list[str]:
    """Checkpoint text as list items: one per line, bullets and numbers removed."""
    items = []
    for line in (text or "").splitlines():
        line = BULLET.sub("", line).strip()
        if line:
            items.append(line)
    return items


# A ref and the bare numbers listed after it: "CAMP-449, 432, 441-444/450 and 452".
# A bare number listed after a ref: ", 432", "/450", " and 441-444".
BARE = re.compile(r"\s*(?:,|/|&|\+|\band\b|\bor\b)\s*(\d+)(?:\s*[-–]\s*(\d+))?\b(?![.%,]\d)")
# What may follow a listed number: another separator, a closing bracket, the end.
LIST_GOES_ON = re.compile(r"\s*(?:[,;/&+)\]:]|\.(?:\s|$)|\band\b|\bor\b|\bplus\b|$)")
# Words that make a number a count, not a task: "CAMP-449, 200 tests pass".
UNIT = re.compile(
    r"\s*(?:px|%|ms|s|x|fps|mb|kb|gb|k|tests?|checks?|keys|lines?|files?|pages?|commits?|"
    r"times?|errors?|warnings?|items?|steps?|seconds?|minutes?|hours?|days?)\b",
    re.IGNORECASE,
)
# The word after a listed number, and the words that let a list go on past one.
NEXT_WORD = re.compile(r"\s*([^\W\d_][\w'-]*)")
JOINS = {"with", "plus", "and", "or"}
SPAN = re.compile(r"\s*(?:to|through|–|—)\s*([A-Z][A-Z0-9]{1,15})-(\d+)\b")
# "Stays in review." says where the task is, not what was done.
STATUS_ONLY = re.compile(
    r"^(?:it\s+)?(?:stays|is|was|set|moved|went|goes|now)?\s*(?:to|in|into)?\s*(?:review|done)\.?$",
    re.IGNORECASE,
)
# Commit hashes and brackets holding only refs say nothing a person reads as work.
HASH = re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b")
WORD = re.compile(r"[^\W\d_]{2,}")
FILLER = {"and", "or", "with", "plus", "the", "an", "of", "for", "to", "in", "on"}
MAX_RANGE = 20
# What may stand between a task and a ref of another kind that a list of numbers carries on past.
CARRY_ON = {",", "/", "&", "+", "", "with", "and"}
# A line shared by several tasks longer than this loses its list of refs.
SHARED_MAX = 120


@dataclass
class Mark:
    """Where the text names a task: a full ref, or a bare number listed after one."""

    start: int
    end: int
    ref: str


def _listed(text: str, bare: re.Match, width: int) -> bool:
    """Whether a number after a separator is a task: the list goes on after it, or it has the
    task numbers' width and what follows joins it to more ("CAMP-448, 435 with the recheck").
    Any other word after it makes it a count: ", 218 px", "PROJ-041, 380 passed", "CAMP-100,
    250 frontend"."""
    if LIST_GOES_ON.match(text, bare.end()):
        return True
    if len(bare.group(1)) != width or UNIT.match(text, bare.end()):
        return False
    after = NEXT_WORD.match(text, bare.end())
    return after is None or after.group(1).casefold() in JOINS


def marks(text: str | None, prefix: str) -> list[Mark]:
    """Every place the text names one of the project's tasks, bare numbers included: in
    "CAMP-449, 432 and 441" the 432 is CAMP-432. A number with a unit after it ("CAMP-5, 218 px")
    is not a task. Refs of other kinds (DEC-12, BUG-3) don't name tasks, though a list of
    numbers that started with a task carries on past them ("CAMP-456, BUG-175, 450")."""
    text = text or ""
    found: list[Mark] = []
    position = 0
    while (match := TASK_REF.search(text, position)) is not None:
        position = match.end()
        if match.group(1) == prefix:
            found.append(Mark(match.start(), match.end(), match.group(0)))
            width = len(match.group(2))
            if (span := SPAN.match(text, position)) and span.group(1) == prefix:
                # "CAMP-415 to CAMP-426": the tasks between are named too.
                low, high = int(match.group(2)), int(span.group(2))
                if 0 < high - low <= MAX_RANGE:
                    for number in range(low + 1, high):
                        ref = f"{prefix}-{str(number).zfill(width)}"
                        found.append(Mark(match.end(), span.start(1), ref))
        elif found and text[found[-1].end : match.start()].strip() in CARRY_ON:
            width = len(found[-1].ref.rsplit("-", 1)[1])
        else:
            continue
        while (bare := BARE.match(text, position)) is not None and _listed(text, bare, width):
            first = int(bare.group(1))
            last = int(bare.group(2) or first)
            numbers = range(first, last + 1) if 0 <= last - first <= MAX_RANGE else [first]
            for number in numbers:
                digits = str(number).zfill(width)
                found.append(Mark(bare.start(1), bare.end(), f"{prefix}-{digits}"))
            position = bare.end()
    return found


def task_refs(text: str | None, prefix: str) -> set[str]:
    """The project's task refs named in the text (CAMP-452, not DEC-12 or BUG-3), with bare
    numbers listed after one ("CAMP-449, 452") counted too."""
    return {mark.ref for mark in marks(text, prefix)}


def _split(text: str, lo: int, hi: int) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """text[lo:hi] split at commas and semicolons outside brackets, and the outermost bracketed
    groups in it (what is inside them), as (start, end) offsets into text."""
    items, groups, depth, start, opened = [], [], 0, lo, lo
    for index in range(lo, hi):
        char = text[index]
        if char in "([":
            if depth == 0:
                opened = index + 1
            depth += 1
        elif char in ")]" and depth:
            depth -= 1
            if depth == 0:
                groups.append((opened, index))
        elif char in ",;" and depth == 0:
            items.append((start, index))
            start = index + 1
    items.append((start, hi))
    return items, groups


def _clean(text: str) -> str:
    """An item with its task refs already blanked: commit hashes, brackets holding only refs
    ("(DEC-12)"), refs of other kinds at its edges ("/DEC-184") and loose punctuation go too."""
    text = HASH.sub(" ", text)
    token = r"(?:[A-Z][A-Z0-9]{1,15}-\d+|[,;/&+:.–—-]|\band\b|\bwith\b|\s)"
    edge = r"(?:[\s,/&+]*[A-Z][A-Z0-9]{1,15}-\d+)+[\s,/&+]*"
    previous = None
    while previous != text:
        previous = text
        text = re.sub(rf"[(\[]{token}*[)\]]", " ", text)
        text = re.sub(r"[(\[]\s*[,/&+]\s*", "(", text)
        text = re.sub(r"\s*[,/&+]\s*(?=[)\]])", "", text)
        text = re.sub(rf"^{edge}|{edge}$", " ", text.strip())
        text = re.sub(r"\s*(?:[,/&+]\s*)+$", "", text)
        text = TRAILING.sub("", LEADING.sub("", text.strip()))
    text = re.sub(r"\s{2,}", " ", text)
    if text.endswith(")") and text.count(")") > text.count("("):
        text = text[:-1].rstrip()
    return text


def _blank(text: str, lo: int, hi: int, found: list[Mark]) -> str:
    """text[lo:hi] with the places it names tasks blanked out (bare numbers too)."""
    chars = list(text[lo:hi])
    for mark in found:
        for index in range(max(mark.start, lo), min(mark.end, hi)):
            chars[index - lo] = " "
    return "".join(chars)


def _words(text: str) -> list[str]:
    """The words that carry meaning: not refs, and not "and", "with", "the"."""
    return [w for w in WORD.findall(TASK_REF.sub(" ", text)) if w.lower() not in FILLER]


def _says_something(text: str) -> bool:
    """At least two words: a lone "Icon" or "Pluck" says nothing the task's title doesn't."""
    return len(_words(text)) >= 2


def _from_colon(text: str, lo: int, first: int) -> int:
    """Where an item starting at lo really starts: after the last colon (outside brackets)
    before the ref at first. In "Camp batch: CAMP-4 bedroll goal" the words before the colon
    head the whole list, not this task."""
    depth, cut = 0, lo
    for index in range(lo, first):
        char = text[index]
        if char in "([":
            depth += 1
        elif char in ")]":
            depth = max(0, depth - 1)
        elif char == ":" and depth == 0:
            cut = index + 1
    return cut


def _shared(text: str, lo: int, hi: int, ref: str, found: list[Mark]) -> str:
    """An item shared with other tasks, as one line: a long list of refs in it is dropped."""
    line = text[lo:hi]
    if len(line.strip()) > SHARED_MAX:
        _, groups = _split(text, lo, hi)
        for a, b in reversed(groups):
            if any(m.ref == ref and a <= m.start < b for m in found):
                line = line[: a - 1 - lo] + line[b + 1 - lo :]
    return TRAILING.sub("", LEADING.sub("", re.sub(r"\s{2,}", " ", line.strip())))


def _heads_a_list(text: str, end: int, hi: int, ref: str, found: list[Mark]) -> bool:
    """Whether the item ending at end closes on this task and the next item starts with a ref:
    in "Owner review of CAMP-381, CAMP-382, BUG-135" the words before the first ref are about
    the whole list (unlike "pluck CAMP-264, Plants nature CAMP-229")."""
    last = max(
        (m for m in found if m.end <= end and m.start < end), key=lambda m: m.end, default=None
    )
    if last is None or last.ref != ref or text[last.end : end].strip(" .)]"):
        return False
    rest = text[end + 1 : hi].lstrip()
    return bool(TASK_REF.match(rest))


def _part(text: str, lo: int, hi: int, ref: str, found: list[Mark]) -> str | None:
    """What text[lo:hi] says about this task alone (see _own_part). None: the task is only
    listed there; "": it is named with words, but too few to say anything."""
    parts: list[str] = []
    listed = False
    items, groups = _split(text, lo, hi)
    for start, end in items:
        named = {m.ref for m in found if start <= m.start < end}
        if ref not in named:
            continue
        first = next(m.start for m in found if m.ref == ref and start <= m.start < end)
        if named == {ref}:
            words = _clean(_blank(text, _from_colon(text, start, first), end, found))
            if _heads_a_list(text, end, hi, ref, found):
                listed = True
            elif _says_something(words):
                parts.append(words)
            elif not _words(words):
                listed = True
            continue
        inner = next(
            ((a, b) for a, b in groups if start <= a and b <= end and a <= first < b), None
        )
        own = _part(text, inner[0], inner[1], ref, found) if inner else None
        if own:
            parts.append(own)
        elif own is None:
            begin = _from_colon(text, start, first)
            if _says_something(_clean(_blank(text, begin, end, found))):
                parts.append(_shared(text, begin, end, ref, found))
    if parts:
        return "; ".join(dict.fromkeys(parts))
    return None if listed else ""


def _own_part(sentence: str, ref: str, prefix: str) -> str:
    """From a sentence naming several tasks, what it says about this one: the list item that
    names only this task, with the ref taken out ("CAMP-449 bedroll goal" or "bedroll goal
    CAMP-449" both read "bedroll goal"). Where the task is only listed with others
    ("build-13 camp (CAMP-449, 432, 441)"), the item they share is kept, but a bare list of
    refs says nothing, and neither does a lone word ("pluck CAMP-264")."""
    return _part(sentence, 0, len(sentence), ref, marks(sentence, prefix)) or ""


def pick(text: str | None, ref: str, prefix: str, *, filed_here: bool = False) -> list[str]:
    """The lines of a checkpoint field that are about this task (see the module's note). In a
    note filed under this task, text before any task is named is about this task."""
    picked: list[str] = []
    # The task the lines are about until one names another: this one in its own note, then
    # whichever task the last heading ("CAMP-4:") named.
    section: str | None = ref if filed_here else None
    for line in lines(text):
        heading = line.endswith(":") or len(_clean(line).strip(" :;,.-–—")) < 3
        # The task the text is about now: a ref, MIXED, or None for nothing named yet.
        context = section
        kept: list[str] = []
        for sentence in SENTENCE_END.split(line):
            named = task_refs(sentence, prefix)
            if not named:
                if context == ref:
                    kept.append(sentence)
                continue
            if named == {ref}:
                context = ref
                kept.append(sentence)
                continue
            context = MIXED if ref in named else next(iter(named)) if len(named) == 1 else MIXED
            if ref in named and (part := _own_part(sentence, ref, prefix)):
                kept.append(part)
        if heading:
            section = context
        elif kept and not STATUS_ONLY.match(item := _tidy(" ".join(kept), ref)):
            picked.append(item)
    return picked


def _tidy(item: str, ref: str) -> str:
    """ "CAMP-452: badge built" (or "d7ce1e9f CAMP-452: badge built") reads "Badge built" under
    CAMP-452's own review."""
    if (hashed := HASH.match(item)) and item[hashed.end() :].lstrip().startswith(ref):
        item = item[hashed.end() :].lstrip()
    if item.startswith(ref):
        rest = LEADING.sub("", item[len(ref) :])
        while (shorter := LEADING.sub("", rest)) != rest:
            rest = shorter
        if len(rest) >= 3:
            item = rest
    return item[:1].upper() + item[1:]


@dataclass
class Note:
    """One checkpoint, as the Review panel's "The agent's full notes" shows it."""

    title: str
    created_at: object
    agent: str | None
    summary: str
    completed_work: str
    remaining_work: str
    problems: str
    next_steps: str
    task_id: str | None = None

    def text(self) -> str:
        return "\n".join(
            [
                self.title,
                self.summary,
                self.completed_work,
                self.remaining_work,
                self.problems,
                self.next_steps,
            ]
        )


@dataclass
class Picked:
    """A review drafted from notes: what they say was done, what is left, what comes next."""

    summary: str = ""
    done: list[str] = field(default_factory=list)
    not_done: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    agent: str | None = None
    # True when some lines were about other tasks and were left out.
    left_out: bool = False


def _add(items: list[str], new: Sequence[str]) -> None:
    for item in new:
        if item not in items:
            items.append(item)


def draft(notes: Sequence[Note], task_id: str, ref: str) -> Picked:
    """What the notes (newest first) say about this task. Done collects every note's work;
    what is left and the next steps come from the newest note that says anything about it."""
    prefix = ref.rsplit("-", 1)[0]
    result = Picked()
    for note in reversed(notes):  # oldest first, so the list reads in the order work was done
        others = task_refs(note.text(), prefix) - {ref}
        here = note.task_id == task_id
        result.left_out = result.left_out or bool(others)

        def take(text: str, here: bool = here) -> list[str]:
            return pick(text, ref, prefix, filed_here=here)

        done = take(note.completed_work)
        if not done and others:
            # A batch note that names this task only in its summary.
            done = take(note.summary, here=False)
        _add(result.done, done)
        left = take(note.remaining_work) + take(note.problems)
        steps = take(note.next_steps)
        if done or left or steps:
            # The newest note that says anything about this task says what is left of it: an
            # older note's leftovers may since have been done.
            result.not_done, result.next_steps = left, steps
        if here and not others and note.summary.strip():
            result.summary = note.summary.strip()
        result.agent = note.agent or result.agent
    if result.summary in result.done:
        result.done.remove(result.summary)
    return result

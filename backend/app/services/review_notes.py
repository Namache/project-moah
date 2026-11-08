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
LEADING = re.compile(r"^(?:[\s:;,.)\]–—-]+|and\s+)", re.IGNORECASE)
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


def task_refs(text: str | None, prefix: str) -> set[str]:
    """The project's task refs named in the text (CAMP-452, not DEC-12 or BUG-3)."""
    return {m.group(0) for m in TASK_REF.finditer(text or "") if m.group(1) == prefix}


def _own_part(sentence: str, ref: str, prefix: str) -> str:
    """From a sentence naming several tasks, the part from this ref to the next task's ref."""
    parts = []
    marks = [m for m in TASK_REF.finditer(sentence) if m.group(1) == prefix]
    for index, mark in enumerate(marks):
        if mark.group(0) != ref:
            continue
        end = marks[index + 1].start() if index + 1 < len(marks) else len(sentence)
        part = sentence[mark.end() : end]
        previous = None
        while previous != part:
            previous = part
            part = TRAILING.sub("", LEADING.sub("", part))
            if part.endswith(")") and part.count(")") > part.count("("):
                part = part[:-1]
        if len(part) >= 3:
            parts.append(part)
    return "; ".join(parts)


def pick(text: str | None, ref: str, prefix: str, *, filed_here: bool = False) -> list[str]:
    """The lines of a checkpoint field that are about this task (see the module's note). In a
    note filed under this task, text before any task is named is about this task."""
    picked: list[str] = []
    # The task the lines are about until one names another: this one in its own note, then
    # whichever task the last heading ("CAMP-4:") named.
    section: str | None = ref if filed_here else None
    for line in lines(text):
        heading = line.endswith(":") or len(TASK_REF.sub("", line).strip(" :;,.-–—")) < 3
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
        elif kept:
            picked.append(_tidy(" ".join(kept), ref))
    return picked


def _tidy(item: str, ref: str) -> str:
    """ "CAMP-452: badge built" reads "Badge built" under CAMP-452's own review."""
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

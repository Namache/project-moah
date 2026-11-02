"""The short brief an agent reads at the start of every session: the person's global rules, the
current project's rules and state, and how to keep Project Moah up to date.

Kept small on purpose. It is injected once per session, so every line costs tokens in every chat.
Details come later, only when the work needs them, from context packs (see RETRIEVE_WHEN).
The one exception is the unfinished task: its decisions are listed by title, because agents
asked the person again what those records already said (2026-11-02 test).
"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.checkpoint import Checkpoint
from app.models.memory import Memory
from app.models.project import GLOBAL_PROJECT_ID, Project
from app.models.task import AcceptanceCriterion, Task
from app.schemas.memory import MemoryRead
from app.services.graph import MENTION_PATTERN, GraphService, Node
from app.services.memory import IMPORTANCE_RANK, MemoryService
from app.services.proposals import ProposalService

# When an agent should fetch a context pack. The brief lists these, and the retrieval benchmark
# (tests/retrieval_bench.py) replays sessions against the same list, so the two cannot drift.
RETRIEVE_WHEN: dict[str, str] = {
    "continue_task": "you continue unfinished work from an earlier session "
    "(this brief has titles only)",
    "start_task": "you start or switch tasks",
    "names_record": "a request names an ID you have no pack for",
    "history": "you need past decisions, known bugs or traps",
    "unfamiliar_area": "you change an area new to you this session",
    "debugging": "you track down a bug",
}

# Read in every session, so every word costs. The person's own rules often say "ask when
# unsure"; this says where their earlier answers are, so agents look before they ask.
HOW_TO = (
    """\
HOW TO WORK WITH PROJECT MOAH
Follow every rule above. Moah also holds the person's earlier answers.
- Check Moah before you ask the person anything (scope, behaviour, a number, a default):
  brain_context_pack, or brain_search(query="..."). Ask only what Moah and the code leave
  open. Name the record you follow instead of asking ("Following DEC-001").
- Call brain_context_pack when:
"""
    + "\n".join(f"  * {when}" for when in RETRIEVE_WHEN.values())
    + """
  Skip it only for small edits, or when a pack from this session already covers the work.
- Writing to Moah is part of the work and needs no permission. Record the person's answers
  and choices as decisions (brain_create_memory) unless a record already says it, and new
  rules, facts, bugs and warnings with links. Before your final reply on work that changed
  files, call brain_create_checkpoint (done, left, next). After using a pack, call
  brain_retrieval_feedback.
- New global rules and decisions, locked memory and finishing a task need the person's review."""
)

CLOSED_TASK = ("completed", "archived")
# What counts as already decided for a task: settled guidance first, then what is known.
DECIDED_FIRST = ("decision", "rule", "warning")
DECIDED_LATER = ("fact", "bug")
DECIDED_LIMIT = 6
TITLE_LIMIT = 90
LEFT_LIMIT = 300
AGENT_HIDDEN = ("hidden", "manual_only")


def _rule_line(m: MemoryRead, scope: str = "") -> str:
    body = " ".join(m.content.split())
    return f"- {scope}{m.human_id} {m.title}" + (f": {body}" if body else "")


def _visible(records: list[MemoryRead]) -> list[MemoryRead]:
    return [m for m in records if m.ai_visibility not in AGENT_HIDDEN]


def _cut(text: str, limit: int) -> str:
    """Whitespace collapsed, and cut on a word boundary with "..." when longer than ``limit``."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 3]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:.") + "..."


def global_rules(session: Session) -> list[MemoryRead]:
    records = MemoryService(session).list(GLOBAL_PROJECT_ID, statuses=["active"], limit=200)
    rules = [m for m in _visible(records) if m.type == "rule" or m.ai_visibility == "always"]
    return sorted(rules, key=lambda m: m.human_id)


def unfinished_task(session: Session, project: Project, latest: Checkpoint | None) -> Task | None:
    """The task the person is most likely in the middle of: the focus task, else the latest
    checkpoint's task while it is open, else the only task in progress. Never a guess between
    several. Reading it changes nothing: the focus and the session's task stay as they are."""
    if project.current_focus_task_id:
        focus = session.get(Task, project.current_focus_task_id)
        if focus is not None and focus.status not in CLOSED_TASK:
            return focus
    if latest is not None and latest.task_id:
        task = session.get(Task, latest.task_id)
        if task is not None and task.project_id == project.id and task.status not in CLOSED_TASK:
            return task
    started = list(
        session.scalars(
            select(Task).where(Task.project_id == project.id, Task.status == "in_progress").limit(2)
        )
    )
    return started[0] if len(started) == 1 else None


def _latest_checkpoint(
    session: Session, project_id: str, task_id: str | None = None
) -> Checkpoint | None:
    statement = select(Checkpoint).where(Checkpoint.project_id == project_id)
    if task_id is not None:
        statement = statement.where(Checkpoint.task_id == task_id)
    return session.scalars(
        statement.order_by(Checkpoint.created_at.desc(), Checkpoint.id.desc()).limit(1)
    ).first()


def decided_for(
    session: Session, project: Project, task: Task, checkpoint: Checkpoint | None, shown: set[str]
) -> list[Memory]:
    """Settled records for ``task``: those linked to it (stored links and a memory's tasks), and
    those its latest checkpoint, next action or open criteria name. Records in ``shown`` (already
    in the brief) are left out."""
    linked = GraphService(session).linked_memory(project.id, Node("task", task.id))
    texts = [task.next_action or ""]
    if checkpoint is not None:
        texts += [checkpoint.remaining_work, checkpoint.next_steps, checkpoint.problems]
    texts += session.scalars(
        select(AcceptanceCriterion.description).where(
            AcceptanceCriterion.task_id == task.id, AcceptanceCriterion.is_completed.is_(False)
        )
    )
    # "global RULE-3" names a Global record, and every global rule is in the brief already.
    named = {
        m.group("ref").upper()
        for m in MENTION_PATTERN.finditer("\n".join(t for t in texts if t))
        if not m.group("scope")
    }
    if not linked and not named:
        return []
    conditions = []
    if linked:
        conditions.append(Memory.id.in_(linked))
    if named:
        conditions.append(func.upper(Memory.human_id).in_(named))
    found = session.scalars(
        select(Memory).where(
            Memory.project_id == project.id,
            Memory.status == "active",
            Memory.type.in_(DECIDED_FIRST + DECIDED_LATER),
            Memory.ai_visibility.not_in(AGENT_HIDDEN),
            or_(*conditions),
        )
    )
    picked = [
        m for m in found if m.human_id not in shown and not (m.type == "bug" and m.is_resolved)
    ]

    def order(m: Memory) -> tuple:
        prefix, _, number = m.human_id.partition("-")
        return (
            m.type in DECIDED_LATER,
            IMPORTANCE_RANK.get(m.importance, 2),
            prefix,
            int(number) if number.isdigit() else 0,
        )

    return sorted(picked, key=order)[:DECIDED_LIMIT]


def unfinished_lines(
    session: Session, project: Project, task: Task, checkpoint: Checkpoint | None, shown: set[str]
) -> list[str]:
    """The UNFINISHED block. ``checkpoint`` is the task's own latest one, if any."""
    lines = [f"UNFINISHED: {task.human_id} {task.title} ({task.status.replace('_', ' ')})"]
    decided = decided_for(session, project, task, checkpoint, shown)
    if decided:
        lines.append("  Already decided for it (follow these; don't ask the person again):")
        lines += [f"  - {m.human_id} {_cut(m.title, TITLE_LIMIT)}" for m in decided]
    if checkpoint is not None and checkpoint.remaining_work.strip():
        left = _cut(checkpoint.remaining_work, LEFT_LIMIT)
        lines.append(f'  Left to do (checkpoint "{checkpoint.title}"): {left}')
    lines.append(
        f'  Continuing it? Call brain_context_pack(task="{task.human_id}") before you plan or'
        " ask: it has the full records."
    )
    return lines


def build_brief(session: Session, project: Project | None, note: str | None = None) -> str:
    lines = ["PROJECT MOAH BRIEF", "", "GLOBAL RULES (every project, every chat)"]
    rules = global_rules(session)
    # Global IDs are prefixed: projects number their own rules from RULE-001 too.
    lines += [_rule_line(m, "global ") for m in rules] or ["- None yet."]

    if project is None or project.kind == "global":
        if note is None or note.startswith("Unable to safely determine Project Moah project from"):
            note = (
                "No Project Moah project matches this folder, so only the global rules apply. "
                "To use a project, pass project= or add this folder to a project in the app."
            )
        lines += ["", note]
    else:
        lines += ["", f"PROJECT: {project.name} ({project.slug})"]
        if note:
            lines.append(note)
        records = _visible(MemoryService(session).list(project.id, statuses=["active"], limit=300))
        project_rules = [m for m in records if m.type == "rule"][:12]
        standing = [
            m for m in records if m.type in ("decision", "warning") and (m.is_locked or m.is_pinned)
        ][:10]
        if project_rules:
            lines += ["PROJECT RULES"] + [_rule_line(m) for m in project_rules]
        if standing:
            lines += ["KEY DECISIONS AND WARNINGS"]
            lines += [f"- {m.human_id} {m.title}" for m in standing]
        latest = _latest_checkpoint(session, project.id)
        task = unfinished_task(session, project, latest)
        if task is not None:
            shown = {m.human_id for m in project_rules + standing}
            own = latest if latest is not None and latest.task_id == task.id else None
            own = own or _latest_checkpoint(session, project.id, task.id)
            lines += unfinished_lines(session, project, task, own, shown)
        if latest is not None and (task is None or latest.task_id != task.id):
            step = " ".join((latest.next_steps or "").split())[:300]
            nxt = f" (next: {step})" if step else ""
            lines.append(f"LATEST CHECKPOINT: {latest.title}{nxt}")
        pending = ProposalService(session).pending_count(project.id)
        if pending:
            lines.append(f"WAITING FOR THE PERSON'S REVIEW: {pending} proposal(s)")
    lines += ["", HOW_TO]
    return "\n".join(lines)

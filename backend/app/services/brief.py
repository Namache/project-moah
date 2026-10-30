"""The short brief an agent reads at the start of every session: the person's global rules, the
current project's rules and state, and how to keep Project Moah up to date.

Kept small on purpose. It is injected once per session, so every line costs tokens in every chat.
Details come later, on demand, from context packs.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.project import GLOBAL_PROJECT_ID, Project
from app.schemas.memory import MemoryRead
from app.services.checkpoints import CheckpointService
from app.services.memory import MemoryService
from app.services.proposals import ProposalService
from app.services.tasks import TaskService

HOW_TO = """\
HOW TO WORK WITH PROJECT MOAH
Project Moah is the source of truth for rules, decisions and memory, shared by Claude Code
and Codex.
- Follow every rule above. Global rules apply in every project and every chat.
- Call brain_context_pack FIRST for every request, small ones too, before reading code (pass
  cwd or project). The records hold what the code doesn't: known bugs, traps and decisions.
  Then read the files it names. Its task becomes this session's task: what you write afterwards
  is linked to it. Packs leave out the Global rules above, since you already have them.
- As things are settled, record them with brain_create_memory without being asked: decisions,
  rules, facts, bugs and warnings that will matter later. Say how they relate in the same call,
  with related=[IDs] or links=["caused_by DEC-002"]. Skip trivia and anything the code or Git
  history already shows. A record is filed on its shelf automatically; pass shelf= when you know a
  more specific one. Shelves are one shared tree of categories, broad to specific
  (Knowledge > Game development > Game design > Game mechanics), never a project or a word.
  When a pack says a shelf is crowded, split it into narrower categories as it asks.
- After working from a context pack, tell brain_retrieval_feedback which records helped.
- Global memory (project="global") is for things true in every project, such as the person's
  preferences. New global rules and decisions go to brain_create_proposal for the person to
  accept.
- After meaningful work, call brain_create_checkpoint. Locked memory and finishing tasks need
  review."""


def _rule_line(m: MemoryRead, scope: str = "") -> str:
    body = " ".join(m.content.split())
    return f"- {scope}{m.human_id} {m.title}" + (f": {body}" if body else "")


def _visible(records: list[MemoryRead]) -> list[MemoryRead]:
    return [m for m in records if m.ai_visibility not in ("hidden", "manual_only")]


def global_rules(session: Session) -> list[MemoryRead]:
    records = MemoryService(session).list(GLOBAL_PROJECT_ID, statuses=["active"], limit=200)
    rules = [m for m in _visible(records) if m.type == "rule" or m.ai_visibility == "always"]
    return sorted(rules, key=lambda m: m.human_id)


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
        project_rules = [m for m in records if m.type == "rule"]
        standing = [
            m for m in records if m.type in ("decision", "warning") and (m.is_locked or m.is_pinned)
        ]
        if project_rules:
            lines += ["PROJECT RULES"] + [_rule_line(m) for m in project_rules[:12]]
        if standing:
            lines += ["KEY DECISIONS AND WARNINGS"] + [
                f"- {m.human_id} {m.title}" for m in standing[:10]
            ]
        overview = TaskService(session).overviews([project.id])[0]
        if overview.focus_task:
            focus = overview.focus_task
            nxt = f" (next: {focus.next_action})" if getattr(focus, "next_action", None) else ""
            lines.append(f"CURRENT FOCUS: {focus.human_id} {focus.title}{nxt}")
        latest = CheckpointService(session).list(project.id, limit=1)
        if latest:
            step = " ".join((latest[0].next_steps or "").split())[:300]
            lines.append(
                f"LATEST CHECKPOINT: {latest[0].title}" + (f" (next: {step})" if step else "")
            )
        pending = ProposalService(session).pending_count(project.id)
        if pending:
            lines.append(f"WAITING FOR THE PERSON'S REVIEW: {pending} proposal(s)")
    lines += ["", HOW_TO]
    return "\n".join(lines)

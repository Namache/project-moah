"""A vendor-neutral handoff note: what an agent or person needs to pick the work up cold.

Built from the same selection as the context pack, so the two never disagree about which
decisions, issues, and files matter. Plain text, no agent-specific syntax.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.schemas.context import ContextItem
from app.services.checkpoints import CheckpointService
from app.services.context import ContextService, estimate_tokens

PREAMBLE = (
    "Handoff from Project Moah. Treat it as a starting point and check it against the code. "
    "Locked decisions must not be changed without a person's review."
)


def lines(text: str) -> list[str]:
    """Bullet-ready lines from a free-text checkpoint field."""
    out = []
    for raw in text.splitlines():
        cleaned = raw.strip().lstrip("-*• ").strip()
        if cleaned:
            out.append(cleaned)
    return out


class HandoffService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.context = ContextService(session)
        self.checkpoints = CheckpointService(session)

    def build(self, project_id: str, *, task: str | None = None, budget: int = 2000) -> dict:
        project, detail_task, kept, _, _, _, warnings = self.context.assemble(
            project_id, task=task, detail="balanced", budget=budget
        )
        latest = self.checkpoints.list(
            project_id, task=detail_task.human_id if detail_task else None, limit=1
        ) or (self.checkpoints.list(project_id, limit=1) if detail_task else [])
        cp = latest[0] if latest else None

        def section(key: str) -> list[str]:
            return [
                i.text for i in sorted(kept, key=lambda i: (i.order, i.title)) if i.section == key
            ]

        blocks: list[tuple[str, list[str]]] = [("PROJECT", [project.name])]
        if detail_task:
            blocks.append(
                (
                    "TASK",
                    [
                        f"{detail_task.human_id} — {detail_task.title}",
                        f"Status: {detail_task.status.replace('_', ' ').title()}",
                    ],
                )
            )
            done = [c.description for c in detail_task.acceptance_criteria if c.is_completed]
            todo = [c.description for c in detail_task.acceptance_criteria if not c.is_completed]
            completed = [f"✓ {d}" for d in done] + [
                f"- {x}" for x in (lines(cp.completed_work) if cp else [])
            ]
            remaining = [f"✗ {d}" for d in todo] + [
                f"- {x}" for x in (lines(cp.remaining_work) if cp else [])
            ]
            blocks += [
                ("COMPLETED", completed or ["Nothing recorded yet."]),
                ("REMAINING", remaining or ["Nothing recorded as remaining."]),
            ]
            blockers = section("blockers")
            if blockers:
                blocks.append(("BLOCKED BY", blockers))
            next_action = detail_task.next_action or (
                cp.next_steps.strip() if cp and cp.next_steps.strip() else None
            )
            blocks.append(
                ("NEXT ACTION", [next_action or "Not recorded. Decide the next step first."])
            )
        else:
            blocks.append(
                (
                    "TASK",
                    ["No task is in focus. Pick one from the list below."] + section("related"),
                )
            )
        for title, key in (
            ("IMPORTANT DECISIONS", "decisions"),
            ("RULES", "rules"),
            ("WARNINGS", "warnings"),
            ("KNOWN ISSUES", "issues"),
            ("RELEVANT FILES", "files"),
        ):
            found = section(key)
            if found:
                blocks.append((title, found))
        if cp:
            body = [cp.title] + ([cp.summary] if cp.summary.strip() else [])
            if cp.problems.strip():
                body.append(f"Problems: {' '.join(cp.problems.split())}")
            blocks.append(("LATEST CHECKPOINT", body))
        text = (
            PREAMBLE
            + "\n\n"
            + "\n\n".join(f"{title}\n" + "\n".join(body) for title, body in blocks)
        )
        return {
            "project_id": project.id,
            "task": detail_task.human_id if detail_task else None,
            "text": text,
            "estimated_tokens": estimate_tokens(text),
            "warnings": warnings,
            "items": [
                ContextItem(
                    section=i.section,
                    kind=i.kind,
                    ref=i.ref,
                    title=i.title,
                    tokens=estimate_tokens(i.text),
                    reason=i.reason,
                )
                for i in kept
            ],
        }

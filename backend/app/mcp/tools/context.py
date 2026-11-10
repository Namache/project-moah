"""Context packs, feedback on what they held, and the links an agent may confirm."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.mcp.kit import READ, WRITE, ToolKit
from app.models.graph import OPERATIONS
from app.services.context import ContextService
from app.services.discovery import DiscoveryService
from app.services.retrieval import RetrievalService
from app.services.tasks import TaskService
from app.services.update_check import take_daily_check


def register(kit: ToolKit) -> None:
    tool = kit.tool
    pick = kit.pick
    agent = kit.agent
    working = kit.working
    packs = kit.packs
    session_task = kit.session_task
    in_brief = kit.in_brief

    @tool(READ)
    def brain_context_pack(
        session: Session,
        task: str | None = None,
        project: str | None = None,
        detail: str = "balanced",
        budget: int | None = None,
        query: str | None = None,
        include: list[str] | None = None,
        operation: str | None = None,
        explain: bool = False,
        global_rules: bool = False,
        full: bool = False,
    ) -> str:
        """A compact, ranked context pack: the task with its decisions, rules, warnings, bugs,
        files and latest checkpoint. Call it when you continue unfinished work, start or switch
        a task, a request names an ID, you need history or traps, before an unfamiliar area,
        when debugging, and before asking the person a question (query = the question). Skip
        it only for small edits or when a pack from this session already covers the work.
        task is an ID such as CAMP-037; without it, the pack keeps to this session's task, or
        picks the task the work is about, and says which. detail is minimal, balanced or
        detailed. explain=true says why each record came.
        Global rules your brief gave are left out; pass global_rules=true if you never got
        the brief. Project rules come in full when the work needs them.
        The pack's task becomes this session's task. A repeat sends only what is new; full=true
        sends everything again."""
        found, _ = pick(session, project)
        if operation is not None and operation not in OPERATIONS:
            raise ValueError(f"operation must be one of: {', '.join(OPERATIONS)}")
        sent = packs.get(session, found.id)
        if full:
            sent.resend()  # send everything; later repeats count from this pack
        own = working.current(session, found.id)
        pack = ContextService(session).build(
            found.id,
            task=task,
            query=query,
            detail=detail,  # type: ignore[arg-type]
            budget=budget,
            include=include,
            operation=operation,
            record_for=agent,
            global_rules=global_rules,
            sent=sent,
            for_agent=not explain,
            session_task=own.id if own is not None else None,
            # The brief left out of the pack must be one this session got.
            in_brief=not global_rules and in_brief(session, found.id),
        )
        before = own.human_id if own is not None else None
        if pack.task and (pack.task_source != "focus" or not query):
            # The work this pack is for: the task asked for, the session's own, or (with no
            # session task yet) the one the request names or plainly matches. A pack for a
            # search alone only borrows the focus task.
            working.set(found.id, TaskService(session).get(found.id, pack.task).id)
        current = session_task(session, found.id)
        if pack.repeat_of is not None and not pack.retrieval_id:
            # Nothing new: a line, not a pack. The agent already has the rest; the tool's
            # description says how to get it all again (full=true).
            text = pack.text
            if current != before:
                text += f"\nThis session's task is {current}: what you write now is linked to it."
            if check := take_daily_check(session):
                text += "\n\n" + check
            return text
        # The footer keeps to what the agent acts on. Sizes, the kind of work and what was left
        # out are for explain=true.
        footer = list(pack.warnings)
        if explain:
            notes = [f"~{pack.estimated_tokens} tokens", f"operation {pack.operation}"]
            if pack.omitted:
                notes.append(
                    "left out: " + ", ".join(f"{n} {why}" for why, n in pack.omitted.items())
                )
            footer.insert(0, "; ".join(notes) + ".")
        if current and (current != before or pack.repeat_of is None):
            footer.append(f"This session's task is {current}: what you write now is linked to it.")
        if pack.retrieval_id:
            footer.append(
                "When done: brain_create_checkpoint naming the records that helped (counts as"
                " feedback), or brain_retrieval_feedback("
                f'retrieval="R-{pack.retrieval_id[:8]}", useful=[...], not_useful=[...]).'
            )
        if check := take_daily_check(session):
            # The day's check had not been given yet: this session started without a brief.
            footer.append("\n" + check)
        text = pack.text
        if explain:
            why = [
                f"- {i.title[:70]}"
                + (f" ({round(i.confidence * 100)}%)" if i.confidence else "")
                + f": {i.reason}"
                for i in pack.items
                if i.kind.startswith(("memory", "file"))
            ]
            near = [
                f"- {x.title[:70]}"
                + (f" ({round(x.confidence * 100)}%)" if x.confidence else "")
                + f": {x.reason}"
                for x in pack.excluded
            ]
            text += "\n\nWHY THESE\n" + ("\n".join(why) or "- nothing beyond the task")
            if near:
                text += "\n\nCAME CLOSE, LEFT OUT\n" + "\n".join(near)
        return text + ("\n\n---\n" + "\n".join(footer) if footer else "")

    @tool(WRITE)
    def brain_retrieval_feedback(
        session: Session,
        retrieval: str,
        useful: list[str] | None = None,
        not_useful: list[str] | None = None,
        project: str | None = None,
    ) -> dict:
        """Say which records of a context pack helped (useful) and which were noise
        (not_useful), by ID (DEC-003, file:src/a.gd). retrieval is the R-... id at the end of
        the pack. A checkpoint naming the records that helped already counts them; each verdict
        counts once. Links that brought useful records grow stronger for this kind of work,
        links that brought noise weaker. A useful record the pack missed gets linked to the
        task."""
        if not useful and not not_useful:
            raise ValueError("Name at least one record in useful or not_useful.")
        found, _ = pick(session, project, write=True)
        return RetrievalService(session).feedback(
            found.id,
            retrieval,
            useful=useful or [],
            not_useful=not_useful or [],
            actor=agent,
            session_refs=packs.get(session, found.id).retrievals,
        )

    @tool(READ)
    def brain_link_review(session: Session, project: str | None = None) -> dict:
        """What the Link System is unsure about: candidate links it inferred but nobody has
        confirmed, and orphan memory with no links or shelf. Confirm a candidate by asserting it
        with brain_link; reject it with brain_link(remove=true). Also the graph's health and
        shelves the brain suggests growing or merging; those are for the person to accept in
        the app."""
        from app.services.health import HealthService

        found, _ = pick(session, project)
        service = DiscoveryService(session)
        health = HealthService(session)
        stats = health.project(found.id)
        return {
            "health": {k: v for k, v in stats.items() if k not in ("density", "clusters")},
            "shelf_suggestions": [s["message"] for s in health.suggestions(found.id)],
            "candidates": [
                {
                    "link": f"{c['source'].label} {c['relationship']} {c['target'].label}",
                    "titles": f"{c['source'].title} / {c['target'].title}",
                    "confidence": c["confidence"],
                    "why": c["why"],
                }
                for c in service.candidates(found.id, limit=30)
            ],
            "orphans": [
                f"{o['id']} ({o['type']}): {o['title']}"
                for o in service.orphans(found.id, limit=30)
            ],
        }

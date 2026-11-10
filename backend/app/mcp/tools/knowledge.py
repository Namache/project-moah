"""Memory, links, shelves and proposals."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException

from app.mcp.hints import possible_duplicates
from app.mcp.kit import READ, WRITE, ToolKit
from app.mcp.linking import link_written, sort_named
from app.mcp.reviews import REVIEW_DRAFTED
from app.models.memory import Memory
from app.models.project import GLOBAL_PROJECT_ID, Project
from app.schemas.graph import ShelfUpdate
from app.schemas.memory import MemoryCreate, MemorySupersede, MemoryUpdate
from app.schemas.proposal import ProposalCreate
from app.schemas.task import TaskUpdate
from app.services.context import ContextService
from app.services.graph import GraphService
from app.services.memory import MemoryService
from app.services.proposals import ProposalService
from app.services.reviews import ReviewService
from app.services.shelves import ShelfService
from app.services.tasks import TaskService

GLOBAL_PERSON_TYPES = ("rule", "decision")

GLOBAL_RULE_MESSAGE = (
    "Global rules and decisions are the person's to set. Suggest it with "
    'brain_create_proposal(proposal_type="{kind}", project="global").'
)


def refuse_global_rule(project: Project, memory: Memory) -> None:
    """Agents may not change a global rule or decision directly; it must be proposed."""
    if project.kind == "global" and memory.type in GLOBAL_PERSON_TYPES:
        raise ValueError(GLOBAL_RULE_MESSAGE.format(kind="update_memory"))


def register(kit: ToolKit) -> None:
    tool = kit.tool
    pick = kit.pick
    agent = kit.agent
    working = kit.working
    file_on_shelf = kit.file_on_shelf

    @tool(WRITE)
    def brain_create_memory(
        session: Session,
        type: str,
        title: str,
        content: str = "",
        project: str | None = None,
        importance: str = "normal",
        tags: list[str] | None = None,
        tasks: list[str] | None = None,
        related: list[str] | None = None,
        links: list[str] | None = None,
        shelf: str | None = None,
    ) -> dict:
        """Record a decision, rule, fact, idea, bug, note or warning as soon as it is settled, without
        being asked. A rule's title is at most 120 characters, its text 1,200. shelf files it on the shelf of knowledge it belongs to (a name or path,
        project shelf or shared tree); without one, a likely shelf is suggested. related names records it relates to (DEC-003, a task, file:src/a.gd); tasks
        names the tasks it applies to; links adds typed links, each written "relationship
        target" ("caused_by DEC-002", "resolved_by PROJ-6"). Without tasks, it is linked to this
        session's task. Records its text names are linked too. A name that matches nothing is
        reported in not_linked, and the memory is still saved. possible_duplicates lists records
        of the same type with similar titles. Agent-created memory is unlocked and marked as
        agent-written. An idea is never a requirement. project="global" is for
        memory true in every project; global rules and decisions must be proposed with
        brain_create_proposal instead."""
        found, _ = pick(session, project, write=True)
        if found.kind == "global" and type in GLOBAL_PERSON_TYPES:
            raise ValueError(GLOBAL_RULE_MESSAGE.format(kind="create_memory"))
        named = sort_named(session, found.id, [*(related or []), *(tasks or [])])
        created = MemoryService(session).create(
            found.id,
            MemoryCreate(
                type=type,
                title=title,
                content=content,
                importance=importance,  # type: ignore[arg-type]
                tags=tags or [],
                task_ids=named.tasks,
                related=named.memories,
            ),
            actor=agent,
        )
        linked = link_written(
            session,
            found.id,
            f"memory:{created.id}",
            actor=agent,
            links=[*named.links, *(links or [])],
            session_task=None if created.tasks else working.current(session, found.id),
            not_linked=named.not_linked,
        )
        return {
            "created": created.human_id,
            "type": created.type,
            "title": created.title,
            "linked_to": [r.human_id for r in created.related],
            "tasks": [t.human_id for t in created.tasks],
            **file_on_shelf(session, found.id, created.id, f"{title} {content}", shelf),
            **linked,
            **possible_duplicates(session, found.id, created.id, created.type, created.title),
        }

    @tool(WRITE)
    def brain_link_memories(
        session: Session, memory: str, related: list[str], project: str | None = None
    ) -> dict:
        """Link a memory to other memories of the same project (IDs such as DEC-003), so a context
        pack that includes one brings the others. Links never change the records themselves."""
        if not related:
            raise ValueError("Give at least one memory ID to link to.")
        found, _ = pick(session, project, write=True)
        service = MemoryService(session)
        for ref in related:
            result = service.link(found.id, memory, ref, actor=agent)
        return {"memory": result.human_id, "linked_to": [r.human_id for r in result.related]}

    @tool(READ)
    def brain_links(session: Session, node: str | None = None, project: str | None = None) -> dict:
        """What a record connects to, and how. node is a human ID (PB-12, DEC-003) or kind:value
        (task:PB-12, memory:DEC-003, file:src/a.py, shelf:Inventory). Each link reads from that
        record: "uses", "used_by", "governed_by". Omit node to list the relationship types."""
        found, _ = pick(session, project)
        service = GraphService(session)
        if node is None:
            return {
                "relationships": [
                    {"name": r.name, "inverse": r.inverse, "group": r.group}
                    for r in service.relationship_types()
                ]
            }
        result = service.node_links(found.id, node)
        return {
            "node": f"{result.node.label}: {result.node.title}",
            "links": [
                {
                    "relationship": x.relationship,
                    "node": f"{x.node.kind}:{x.node.label}",
                    "title": x.node.title,
                    "strength": x.strength,
                    "confidence": x.confidence,
                    "status": x.status,
                    "why": "; ".join(p.get("detail", "") for p in x.provenance[-2:]),
                    "link_id": x.id,
                }
                for x in result.links
            ],
        }

    @tool(WRITE)
    def brain_link(
        session: Session,
        source: str,
        relationship: str,
        target: str,
        project: str | None = None,
        strength: float | None = None,
        note: str | None = None,
        remove: bool = False,
    ) -> dict:
        """Record how two records of one project relate, as a typed link: source relationship
        target, e.g. ("file:ui/grid.gd", "uses", "file:inventory_manager.gd") or ("BUG-004",
        "caused_by", "DEC-002"). Use brain_links without a node for the relationship types;
        negative ones (independent_of, must_not_depend_on) keep records apart. strength is 0-1:
        0.3 useful, 0.5 relevant, 0.7 strong, 0.9 critical. remove=true deletes the link; links a
        person made cannot be removed by an agent. Removing an inferred link rejects it so it
        is not proposed again; asserting a candidate link confirms it. Name a Global record as
        global:RULE-3 to route it into this project; another project's records cannot be
        linked."""
        found, _ = pick(session, project, write=True)
        service = GraphService(session)
        if remove:
            existing = service.find_link(found.id, source, relationship, target)
            if existing is None:
                raise ValueError("No stored link matches. Built-in links are removed where made.")
            if existing.created_by == "user":
                raise ValueError(
                    "A person made this link. Suggest removing it with brain_create_proposal."
                )
            service.unlink(found.id, existing.id, actor=agent)
            return {"removed": f"{source} {relationship} {target}"}
        edge = service.link(
            found.id,
            source,
            relationship,
            target,
            strength=strength,
            note=note,
            created_by="system",
            actor=agent,
        )
        read = service.link_read(found.id, edge)
        return {
            "linked": f"{source} {relationship} {target}",
            "stored_as": edge.relationship,
            "strength": edge.strength,
            "confidence": edge.confidence,
            "target": read.node.title,
        }

    @tool(READ)
    def brain_shelves(
        session: Session,
        project: str | None = None,
        shelf: str | None = None,
        task: str | None = None,
        text: str | None = None,
    ) -> dict:
        """Shelves: the tree of knowledge records are filed on, from broad to specific
        (Knowledge > Game development > Game design > Game mechanics). The shared tree is one
        for every project, and each project sees only its own records on it; a project may keep
        shelves of its own too. With shelf (a name or path), its records. With task or text, how
        strongly that work wakes each shelf."""
        found, _ = pick(session, project)
        service = ShelfService(session)
        if shelf is not None:
            chosen = service.find(found.id, shelf)
            nodes = service.memberships(chosen.project_id, [chosen], for_project=found.id)
            info = service.graph.describe(found.id, nodes[chosen.id])
            return {
                "shelf": service.path(chosen),
                "keywords": [k for k in chosen.keywords.split(",") if k],
                "members": sorted(f"{i.node.kind}:{i.label} {i.title}" for i in info.values()),
            }
        if task is not None or text is not None:
            activations = ContextService(session).shelf_activation(found.id, task=task, query=text)
            return {
                "activation": [
                    {
                        "shelf": a.path or a.name,
                        "shared": a.scope == "global",
                        "activation": a.activation,
                        "active": a.active,
                        "why": a.reason,
                    }
                    for a in activations
                    if a.activation > 0 or a.scope == "project"
                ]
            }
        own = service.list(found.id)
        shelves, members = service.shared(found.id)
        # In path order, so each shelf comes right after the one it sits on and the list reads
        # as the tree it is.
        return {
            "shared_tree": sorted(
                (
                    {"shelf": service.path(s), "records": len(members.get(s.id, ())), "keywords": k}
                    for s in shelves
                    for k in [[w for w in s.keywords.split(",") if w]]
                ),
                key=lambda row: [part.casefold() for part in row["shelf"].split(" > ")],
            ),
            "project_shelves": sorted(
                (
                    {
                        "shelf": service.path(service.get(found.id, s.id)),
                        "keywords": s.keywords,
                        "records": s.member_count,
                    }
                    for s in own
                ),
                key=lambda row: [part.casefold() for part in row["shelf"].split(" > ")],
            ),
        }

    @tool(WRITE)
    def brain_update_shelf(
        session: Session,
        shelf: str,
        project: str | None = None,
        shared: bool = False,
        keywords: list[str] | None = None,
        description: str | None = None,
        parent: str | None = None,
        add: list[str] | None = None,
        remove: list[str] | None = None,
        delete: bool = False,
    ) -> dict:
        """File records on a shelf, or create or change one. shelf is a name or a path
        ("Knowledge > Software engineering > Frontend"); a missing shelf along a path is
        created. shared puts a new shelf on the shared tree every project uses (prefer it:
        categories are knowledge, not projects); otherwise a named shelf is looked up in the
        project, then the shared tree. add and remove take the project's records (human IDs or
        kind:value), which stay in their project. delete removes the shelf, never its records.
        Tagging a record with a shelf's name also puts it on the shelf."""
        found, _ = pick(session, project, write=True)
        service = ShelfService(session)
        home = GLOBAL_PROJECT_ID if shared else found.id
        try:
            chosen = service.get(home, shelf) if shared else service.find(found.id, shelf)
            if (
                ">" in shelf
                and service.path(chosen).casefold()
                != " > ".join(n.strip() for n in shelf.split(">")).casefold()
            ):
                chosen = service.ensure_path(home, shelf, keywords=keywords, actor=agent)
        except HTTPException:
            chosen = service.ensure_path(home, shelf, keywords=keywords, actor=agent)
        if delete:
            path = service.path(chosen)
            service.delete(chosen.project_id, chosen.id, actor=agent)
            return {"deleted": path}
        changes = {
            k: v
            for k, v in {"keywords": keywords, "description": description, "parent": parent}.items()
            if v is not None
        }
        if changes:
            service.update(chosen.project_id, chosen.id, ShelfUpdate(**changes), actor=agent)
        if add:
            service.place(found.id, chosen.id, add, actor=agent)
        if remove:
            service.place(found.id, chosen.id, remove, remove=True, actor=agent)
        nodes = service.memberships(chosen.project_id, [chosen], for_project=found.id)
        return {
            "shelf": service.path(chosen),
            "shared": chosen.project_id == GLOBAL_PROJECT_ID,
            "keywords": [k for k in chosen.keywords.split(",") if k],
            "records": len(nodes[chosen.id]),
        }

    @tool(WRITE)
    def brain_update_memory(
        session: Session,
        memory: str,
        project: str | None = None,
        title: str | None = None,
        content: str | None = None,
        importance: str | None = None,
        tags: list[str] | None = None,
        resolved: bool | None = None,
        links: list[str] | None = None,
    ) -> dict:
        """Edit an unlocked memory. Locked memory is refused: propose the change instead.

        Set resolved on a known issue (type bug) to mark it resolved or pending again. links adds
        typed links, each written "relationship target" ("resolved_by PROJ-6"); links describe a
        record without changing it, so they can be added to locked memory too. Records the new
        text names are linked.
        """
        found, _ = pick(session, project, write=True)
        changes = {
            k: v
            for k, v in dict(
                title=title,
                content=content,
                importance=importance,
                tags=tags,
                is_resolved=resolved,
            ).items()
            if v is not None
        }
        if not changes and not links:
            raise ValueError("Give at least one field to change.")
        service = MemoryService(session)
        record = service.get(found.id, memory)
        if changes:
            refuse_global_rule(found, record)
            updated = service.update(
                found.id, memory, MemoryUpdate.model_validate(changes), actor=agent
            )
        else:
            updated = service.read(found.id, record.id)
        return {
            "updated": updated.human_id,
            "title": updated.title,
            **link_written(
                session, found.id, f"memory:{updated.id}", actor=agent, links=links or []
            ),
        }

    @tool(WRITE)
    def brain_supersede_memory(
        session: Session,
        memory: str,
        title: str,
        content: str = "",
        project: str | None = None,
        links: list[str] | None = None,
    ) -> dict:
        """Replace an unlocked memory with a newer one. The old one is kept as history, and the
        new one keeps its links. links adds typed links, each written "relationship target"."""
        found, _ = pick(session, project, write=True)
        service = MemoryService(session)
        refuse_global_rule(found, service.get(found.id, memory))
        new = service.supersede(
            found.id, memory, MemorySupersede(title=title, content=content), actor=agent
        )
        return {
            "created": new.human_id,
            "replaces": memory,
            **link_written(
                session,
                found.id,
                f"memory:{new.id}",
                actor=agent,
                links=links or [],
                session_task=None if new.tasks else working.current(session, found.id),
            ),
        }

    @tool(WRITE)
    def brain_create_proposal(
        session: Session,
        proposal_type: str,
        reason: str,
        target: str | None = None,
        payload: dict[str, Any] | None = None,
        project: str | None = None,
    ) -> dict:
        """Suggest a change for a person to review: create_memory, update_memory, supersede_memory,
        update_task, add_acceptance_criterion, associate_file, or create_bug. Use this for locked
        memory and global rules. Nothing changes until it is accepted. A finished task goes to
        the person with brain_submit_review instead."""
        found, _ = pick(session, project, write=True)
        if proposal_type == "complete_task" and target:
            moved = TaskService(session).update(found.id, target, TaskUpdate(status="review"))
            reported = ReviewService(session).submitted_review(moved.id) is not None
            return {
                "applied": False,
                "status": moved.status,
                "message": f"{moved.human_id} waits in the person's Review screen."
                if reported
                else REVIEW_DRAFTED.format(task=moved.human_id),
            }
        p = ProposalService(session).create(
            found.id,
            ProposalCreate(
                proposal_type=proposal_type,
                target=target,
                payload=payload or {},  # type: ignore[arg-type]
                reason=reason,
            ),
            agent=agent,
        )
        return {
            "proposal": p.human_id,
            "status": p.status,
            "changes": p.changes,
            "message": "Recorded. A person will review it in Project Moah.",
        }

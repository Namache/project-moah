"""The Project Moah MCP server (stdio). One small tool set for retrieving and recording work.

Rules this adapter keeps:
- Agents never silently change locked memory or complete tasks. Those become proposals.
- Every write is attributed to the agent named in the server's settings.
- A project is chosen explicitly, or from the working directory only when unambiguous.
- Errors say what to do next; no stack traces reach the agent.
"""

from __future__ import annotations

import argparse
import base64
import sys
from collections.abc import Callable
from functools import wraps
from typing import Any

from fastapi import HTTPException
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ImageContent, TextContent, ToolAnnotations
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_database_url
from app.db.migrate import upgrade_database
from app.db.session import make_engine, make_session_factory
from app.mcp.linking import SessionTask, link_written, sort_named
from app.mcp.projects import ProjectChoiceError, resolve_project
from app.models.graph import OPERATIONS
from app.models.memory import Memory
from app.models.project import GLOBAL_PROJECT_ID, Project
from app.models.task import Task
from app.schemas.checkpoint import CheckpointCreate
from app.schemas.graph import ShelfUpdate
from app.schemas.memory import HUMAN, MemoryCreate, MemorySupersede, MemoryUpdate
from app.schemas.proposal import ProposalCreate
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.activity import acting_as
from app.services.agent_prompts import second_opinion
from app.services.agent_sync import sync_quietly
from app.services.brief import build_brief
from app.services.checkpoints import CheckpointService
from app.services.context import ContextService
from app.services.discovery import DiscoveryService, discover_checkpoint_quietly
from app.services.files import FileService
from app.services.graph import GraphService, Node
from app.services.images import ImageService
from app.services.memory import MemoryService
from app.services.projects import ProjectService
from app.services.proposals import ProposalService, actor_for
from app.services.retrieval import RetrievalService
from app.services.search import SearchService
from app.services.settings import get_agent_settings
from app.services.shelves import ShelfService
from app.services.tasks import TaskService

INSTRUCTIONS = """\
Project Moah is the person's source of truth for rules, decisions, tasks, checkpoints and memory,
shared by Claude Code and Codex across every project. At the start of a session, call brain_brief
with your working folder as cwd (skip it if a Project Moah brief is already in your context) and
follow the global and project rules it returns. Call brain_context_pack FIRST for every request,
small ones too, before reading code: the records hold what the code doesn't (known bugs, traps,
decisions). The pack's task becomes this session's task, and what you write afterwards is linked
to it.
Record settled decisions, rules, facts, bugs and warnings with brain_create_memory as you go.
When you know how a record relates to others, say so in the same call with links, each written
"relationship target" (links=["caused_by DEC-002", "uses file:src/save.gd"]); use brain_link for
records you did not just write. Link only real relationships, never a rule to everything. A
project record can link to a Global record as global:RULE-3, so that Global knowledge reaches this
project's packs. After working from a context pack, report what helped with
brain_retrieval_feedback. After meaningful work, call brain_create_checkpoint. Locked memory
cannot be changed by you; use brain_create_proposal for a person to review. Completing or
archiving a task also needs review. Ideas are not requirements."""

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
)


GLOBAL_PERSON_TYPES = ("rule", "decision")
GLOBAL_RULE_MESSAGE = (
    "Global rules and decisions are the person's to set. Suggest it with "
    'brain_create_proposal(proposal_type="{kind}", project="global").'
)


def refuse_global_rule(project: Project, memory: Memory) -> None:
    """Agents may not change a global rule or decision directly; it must be proposed."""
    if project.kind == "global" and memory.type in GLOBAL_PERSON_TYPES:
        raise ValueError(GLOBAL_RULE_MESSAGE.format(kind="update_memory"))


def _message(error: Exception) -> str:
    if isinstance(error, HTTPException):
        text = str(error.detail)
        if error.status_code == 423:
            text += " Use brain_create_proposal to suggest the change for a person to review."
        return text
    if isinstance(error, ValidationError):
        first = error.errors()[0]
        return f"Invalid input ({'.'.join(map(str, first['loc']))}: {first['msg']})"
    if isinstance(error, ProjectChoiceError | ValueError):
        return str(error)
    return f"{type(error).__name__}: {error}"


def build_server(
    session_factory: sessionmaker[Session],
    *,
    agent: str = "agent",
    default_project: str | None = None,
) -> MCPServer:
    if agent.strip().casefold() == HUMAN:
        raise ValueError("--agent cannot be 'human': agents are never recorded as a person.")
    server = MCPServer("project-moah", instructions=INSTRUCTIONS)
    actor = actor_for(agent)
    working = SessionTask()

    def tool(annotations: ToolAnnotations):
        """Register a tool that gets a session, attribution, and readable errors."""

        def decorate(fn: Callable[..., Any]):
            @wraps(fn)
            def run(*args: Any, **kwargs: Any) -> Any:
                working.tick()
                with session_factory() as session:
                    try:
                        with acting_as(actor, agent):
                            result = fn(session, *args, **kwargs)
                        return result
                    except Exception as error:  # noqa: BLE001 - turned into a plain message
                        session.rollback()
                        raise ToolError(_message(error)) from None

            # The session is injected, so it must not appear in the tool's schema.
            import inspect

            sig = inspect.signature(fn)
            run.__signature__ = sig.replace(parameters=list(sig.parameters.values())[1:])  # type: ignore[attr-defined]
            return server.tool(annotations=annotations)(run)

        return decorate

    def pick(session: Session, project: str | None, cwd: str | None = None, *, write: bool = False):
        found, how = resolve_project(session, project, cwd, default_project)
        if write and found.status == "archived":
            raise ValueError(f"{found.name} is archived. Ask a person to restore it first.")
        return found, how

    def file_on_shelf(
        session: Session,
        project_id: str,
        memory_id: str,
        text: str,
        shelf: str | None,
        kind: str = "memory",
    ) -> dict:
        """Put a new record on the shelf named, or, when it is on none yet (a tag with a shelf's
        name counts), on the most specific one its words wake."""
        service = ShelfService(session)
        node = f"{kind}:{memory_id}"
        if shelf is not None:
            try:
                return {
                    "shelf": service.path(service.place(project_id, shelf, [node], actor=agent))
                }
            except HTTPException:
                return {"shelf_not_found": shelf}
        own = service.memberships(project_id)
        _, shared = service.shared(project_id)
        if any(Node(kind, memory_id) in nodes for nodes in [*own.values(), *shared.values()]):
            return {}
        best = service.suggest(project_id, text)
        if best is None:
            return {}
        service.place(project_id, best.id, [node], actor=agent)
        return {
            "shelf": ("shared: " if best.scope == "global" else "") + best.path,
            "filed": "automatically; if it belongs elsewhere, move it with brain_update_shelf",
        }

    def session_task(session: Session, project_id: str) -> str | None:
        task = working.current(session, project_id)
        return task.human_id if task else None

    @tool(READ)
    def brain_brief(session: Session, cwd: str | None = None, project: str | None = None) -> str:
        """Start here, once per session. Returns the person's global rules, the project's rules,
        focus and latest checkpoint, and how to keep Project Moah current. Pass your working
        folder as cwd. Works outside any project too: then only global rules apply."""
        working.clear()  # a new session starts with no task of its own
        sync_quietly(session)  # a folder first seen in this session gets its project now
        try:
            found, _ = pick(session, project, cwd)
            note = None
        except ProjectChoiceError as error:
            found, note = None, str(error)
        return build_brief(session, found, note)

    @tool(READ)
    def brain_second_opinion(
        session: Session,
        question: str,
        task: str | None = None,
        project: str | None = None,
        cwd: str | None = None,
    ) -> dict:
        """Use ONLY when the person explicitly asks in this session for a second opinion from the
        other agent (Claude asks Codex; Codex asks Claude). Returns a read-only command to run in
        your terminal, with the question, the task and project context, and how to present and
        save both views. Refused when the person has switched second opinions off."""
        found, _ = pick(session, project, cwd)
        return second_opinion(
            session, get_agent_settings(session), found, agent, question, task, cwd
        )

    @tool(READ)
    def brain_list_projects(session: Session) -> list[dict]:
        """List Project Moah projects, so you can choose one explicitly. Rules and memory for every
        project live in the Global scope: pass project="global"."""
        return [
            {
                "id": p.id,
                "name": p.name,
                "slug": p.slug,
                "status": p.status,
                "repository": p.root_path,
            }
            for p in ProjectService(session).list()
        ]

    @tool(READ)
    def brain_project_state(
        session: Session, project: str | None = None, cwd: str | None = None
    ) -> dict:
        """Identify the project and summarize where work stands: focus task, counts, latest checkpoint,
        pending reviews, and Git status. Pass project, or cwd to match a repository folder."""
        found, how = pick(session, project, cwd)
        tasks = TaskService(session)
        overview = tasks.overviews([found.id])[0]
        latest = CheckpointService(session).list(found.id, limit=1)
        git = FileService(session).git.status(found)
        pending = ProposalService(session).pending_count(found.id)
        return {
            "project": {
                "id": found.id,
                "name": found.name,
                "slug": found.slug,
                "status": found.status,
                "repository": found.root_path,
                "found_by": how,
            },
            "current_focus": overview.focus_task.model_dump(mode="json")
            if overview.focus_task
            else None,
            "milestone": overview.active_milestone.model_dump(mode="json")
            if overview.active_milestone
            else None,
            "task_counts": overview.task_counts,
            "latest_checkpoint": (
                {
                    "id": latest[0].id,
                    "title": latest[0].title,
                    "next_steps": latest[0].next_steps,
                    "remaining_work": latest[0].remaining_work,
                    "task": latest[0].task.human_id if latest[0].task else None,
                }
                if latest
                else None
            ),
            "pending_proposals": pending,
            "session_task": session_task(session, found.id),
            "git": {
                "state": git.state,
                "branch": git.branch,
                "clean": git.clean,
                "changed_files": git.changed_total,
            },
        }

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
    ) -> str:
        """Get a compact, ranked context pack for a task (for example CAMP-037). detail is minimal,
        balanced, or detailed. Omit task to use the project's current focus. operation (coding,
        debugging, design, testing, art, documentation, planning) is detected from the task when
        omitted. explain=true adds why each record was included and what came close. Global rules are left out
        because the session brief already gave them; pass global_rules=true if you never got the
        brief. The task
        becomes this session's task: what you write afterwards is linked to it. The pack
        carries a retrieval id: after the work, report what helped with brain_retrieval_feedback."""
        found, _ = pick(session, project)
        if operation is not None and operation not in OPERATIONS:
            raise ValueError(f"operation must be one of: {', '.join(OPERATIONS)}")
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
        )
        if pack.task and (task or not query):
            # The work this pack is for. A pack for a search alone only borrows the focus task.
            working.set(found.id, TaskService(session).get(found.id, pack.task).id)
        notes = [f"~{pack.estimated_tokens} tokens", f"operation {pack.operation}"] + pack.warnings
        if pack.omitted:
            notes.append("left out: " + ", ".join(f"{n} {why}" for why, n in pack.omitted.items()))
        after = []
        if pack.retrieval_id:
            notes.append(f"retrieval R-{pack.retrieval_id[:8]}")
            after.append(
                f'After the work, call brain_retrieval_feedback(retrieval="R-{pack.retrieval_id[:8]}",'
                " useful=[...], not_useful=[...]) with the IDs that helped and those that did not."
            )
        if current := session_task(session, found.id):
            after.append(f"This session's task is {current}: what you write now is linked to it.")
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
        return f"{text}\n\n---\n" + "; ".join(notes) + "".join(f"\n{line}" for line in after)

    @tool(WRITE)
    def brain_retrieval_feedback(
        session: Session,
        retrieval: str,
        useful: list[str] | None = None,
        not_useful: list[str] | None = None,
        project: str | None = None,
    ) -> dict:
        """After working from a context pack, say which records helped (useful) and which were
        noise (not_useful), by ID (DEC-003, file:src/a.gd). retrieval is the R-... id at the end
        of the pack. Links that brought useful records grow stronger for this kind of work;
        links that brought noise grow weaker for it. A useful record the pack missed gets linked
        to the task, so the next pack finds it."""
        if not useful and not not_useful:
            raise ValueError("Name at least one record in useful or not_useful.")
        found, _ = pick(session, project, write=True)
        return RetrievalService(session).feedback(
            found.id, retrieval, useful=useful or [], not_useful=not_useful or [], actor=agent
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

    @tool(READ)
    def brain_get_task(session: Session, task: str, project: str | None = None) -> dict:
        """Full detail for one task: description, acceptance criteria, relationships, and milestone."""
        found, _ = pick(session, project)
        return TaskService(session).detail(found.id, task).model_dump(mode="json")

    @tool(READ)
    def brain_view_images(session: Session, record: str, project: str | None = None) -> list:
        """See the images a person attached to a task or memory record (PROJ-6, DEC-3, or one
        image's id). Records that have images list them under images; this returns the pictures
        themselves, so look at them before working from the record."""
        found, _ = pick(session, project)
        service = ImageService(session)
        try:
            one = service.get(found.id, record.strip())
            kind, owner_id = ("task", one.task_id) if one.task_id else ("memory", one.memory_id)
        except HTTPException:
            one = None
            node = GraphService(session).resolve(found.id, record, allow_global=True)
            if node.kind not in ("task", "memory"):
                raise ValueError("Only tasks and memory records have images.") from None
            kind, owner_id = node.kind, node.id
        row = session.get(Task if kind == "task" else Memory, owner_id)
        if kind == "memory" and row.ai_visibility == "hidden":
            raise ValueError(f"{row.human_id} is hidden from agents.")
        images = (
            [one]
            if one
            else [
                service.get(row.project_id, ref.id)
                for ref in service.for_records(kind, [owner_id])[owner_id]
            ]
        )
        if not images:
            return [TextContent(type="text", text=f"{row.human_id} has no images.")]
        blocks: list = []
        for index, image in enumerate(images, 1):
            size = f", {image.width}x{image.height}" if image.width else ""
            blocks.append(
                TextContent(
                    type="text",
                    text=f"{row.human_id} image {index} of {len(images)}: {image.filename}"
                    f" ({image.media_type}{size}, id {image.id})",
                )
            )
            blocks.append(
                ImageContent(
                    type="image",
                    data=base64.b64encode(image.data).decode(),
                    mime_type=image.media_type,
                )
            )
        return blocks

    @tool(READ)
    def brain_list_tasks(
        session: Session,
        project: str | None = None,
        status: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """List tasks compactly. status can be backlog, todo, in_progress, blocked, review, completed."""
        found, _ = pick(session, project)
        rows = TaskService(session).list(found.id, statuses=status)[: max(1, min(limit, 200))]
        return [
            {
                "id": t.human_id,
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "criteria": f"{t.criteria_completed}/{t.criteria_total}",
                "focus": t.is_focus,
                "waiting_on_dependency": t.is_blocked_by_open_dependency,
            }
            for t in rows
        ]

    @tool(READ)
    def brain_search(
        session: Session,
        query: str,
        project: str | None = None,
        scope: str = "project",
        types: list[str] | None = None,
        limit: int = 10,
    ) -> dict:
        """Search tasks, memory, checkpoints and files. scope is 'project' (default) or 'all'; results
        from all projects are for reading only and must not be treated as this project's truth."""
        search = SearchService(session)
        if scope == "all":
            result = search.search(
                query, entity_types=types, for_agent=True, limit=max(1, min(limit, 50))
            )
        elif scope == "project":
            found, _ = pick(session, project)
            result = search.search(
                query,
                project_id=found.id,
                entity_types=types,
                for_agent=True,
                limit=max(1, min(limit, 50)),
            )
        else:
            raise ValueError("scope must be 'project' or 'all'")
        return {
            "total": result["total"],
            "results": [
                {
                    k: h[k]
                    for k in (
                        "entity_type",
                        "human_id",
                        "title",
                        "snippet",
                        "status",
                        "project_name",
                    )
                }
                for h in result["items"]
            ],
        }

    @tool(READ)
    def brain_get_related(session: Session, task: str, project: str | None = None) -> dict:
        """Everything linked to a task: related tasks, memory, files, checkpoints, and commits."""
        found, _ = pick(session, project)
        detail = TaskService(session).detail(found.id, task)
        files = FileService(session)
        memory = MemoryService(session).list(found.id, task=detail.id)
        return {
            "task": detail.human_id,
            "relationships": [
                {
                    "type": r.type,
                    "task": r.task.human_id,
                    "title": r.task.title,
                    "status": r.task.status,
                }
                for r in detail.relationships
            ],
            "memory": [
                {
                    "id": m.human_id,
                    "type": m.type,
                    "title": m.title,
                    "locked": m.is_locked,
                    "visibility": m.ai_visibility,
                }
                for m in memory
            ],
            "files": [
                {"path": f.path, "purpose": f.purpose, "why": why}
                for f, why in files.files_for_task(found.id, detail.id)
            ],
            "checkpoints": [
                {"id": c.id, "title": c.title, "summary": c.summary}
                for c in CheckpointService(session).list(found.id, task=detail.id, limit=5)
            ],
            "commits": [
                {"sha": c.short_sha, "subject": c.subject}
                for c in files.commits(found.id, task=detail.id).commits
            ],
        }

    @tool(READ)
    def brain_changed_files(session: Session, project: str | None = None) -> dict:
        """Files changed in the working tree right now, with any notes Project Moah holds about them."""
        found, _ = pick(session, project)
        files = FileService(session)
        git = files.git.status(found)
        notes = {f.path: f for f in files.list(found.id)}
        return {
            "git_state": git.state,
            "message": git.message if git.state != "ok" else None,
            "branch": git.branch,
            "total_changed": git.changed_total,
            "changed": [
                {
                    "path": c.path,
                    "status": c.status,
                    "purpose": notes[c.path].purpose if c.path in notes else None,
                    "tasks": [t.human_id for t in notes[c.path].tasks] if c.path in notes else [],
                }
                for c in git.changed
            ],
        }

    @tool(WRITE)
    def brain_create_task(
        session: Session,
        title: str,
        project: str | None = None,
        description: str | None = None,
        prefix: str | None = None,
        priority: str = "normal",
        status: str = "todo",
        next_action: str | None = None,
        acceptance_criteria: list[str] | None = None,
        tags: list[str] | None = None,
        milestone: str | None = None,
        links: list[str] | None = None,
    ) -> dict:
        """Create a task. It starts as todo or backlog; people decide when work is complete.
        links adds typed links, each written "relationship target" ("caused_by BUG-002"). A task
        created while this session works on another task is linked to that task."""
        found, _ = pick(session, project, write=True)
        if status not in ("backlog", "todo"):
            raise ValueError("New tasks can start as 'backlog' or 'todo'.")
        task = TaskService(session).create(
            found.id,
            TaskCreate(
                title=title,
                description=description,
                prefix=prefix,
                priority=priority,
                status=status,  # type: ignore[arg-type]
                next_action=next_action,
                acceptance_criteria=acceptance_criteria or [],
                tags=tags or [],
                milestone_id=milestone,
            ),
        )
        return {
            "created": task.human_id,
            "title": task.title,
            "status": task.status,
            **file_on_shelf(
                session, found.id, task.id, f"{title} {description or ''}", None, kind="task"
            ),
            **link_written(
                session,
                found.id,
                f"task:{task.id}",
                actor=agent,
                links=links or [],
                session_task=working.current(session, found.id),
            ),
        }

    @tool(WRITE)
    def brain_update_task(
        session: Session,
        task: str,
        project: str | None = None,
        next_action: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        reason: str = "",
        links: list[str] | None = None,
    ) -> dict:
        """Update a task's working fields. Completing or archiving a task is not applied: it becomes a
        proposal for a person to review. Setting status in_progress makes it this session's task.
        links adds typed links, each written "relationship target" ("blocked_by PROJ-4")."""
        found, _ = pick(session, project, write=True)
        changes = {
            k: v
            for k, v in dict(
                next_action=next_action,
                status=status,
                priority=priority,
                description=description,
                tags=tags,
            ).items()
            if v is not None
        }
        if not changes and not links:
            raise ValueError("Give at least one field to change.")
        TaskUpdate.model_validate(changes)
        proposals = ProposalService(session)
        if status == "completed":
            rest = {k: v for k, v in changes.items() if k != "status"}
            # The proposal comes first: if it is refused, nothing else has been applied.
            p = proposals.create(
                found.id,
                ProposalCreate(
                    proposal_type="complete_task",
                    target=task,
                    payload={},
                    reason=reason or "Agent reports the task is complete.",
                ),
                agent=agent,
            )
            if rest:
                TaskService(session).update(found.id, task, TaskUpdate.model_validate(rest))
            return {
                "applied": False,
                "needs_review": True,
                "proposal": p.human_id,
                "message": "Completing a task needs a person's review. A proposal was created.",
                # Links describe the task without changing it, so they need no review.
                **link_written(session, found.id, f"task:{task}", actor=agent, links=links or []),
            }
        if status == "archived":
            p = proposals.create(
                found.id,
                ProposalCreate(
                    proposal_type="update_task",
                    target=task,
                    payload=changes,
                    reason=reason or "Agent suggests archiving.",
                ),
                agent=agent,
            )
            return {
                "applied": False,
                "needs_review": True,
                "proposal": p.human_id,
                "message": "Archiving a task needs a person's review. A proposal was created.",
                **link_written(session, found.id, f"task:{task}", actor=agent, links=links or []),
            }
        tasks = TaskService(session)
        updated = (
            tasks.update(found.id, task, TaskUpdate.model_validate(changes))
            if changes
            else tasks.get(found.id, task)
        )
        if updated.status == "in_progress" and status == "in_progress":
            working.set(found.id, updated.id)
        return {
            "applied": True,
            "task": updated.human_id,
            "status": updated.status,
            **link_written(session, found.id, f"task:{updated.id}", actor=agent, links=links or []),
        }

    @tool(WRITE)
    def brain_create_checkpoint(
        session: Session,
        title: str,
        summary: str = "",
        completed_work: str = "",
        remaining_work: str = "",
        problems: str = "",
        next_steps: str = "",
        task: str | None = None,
        project: str | None = None,
        git_commit: str | None = None,
    ) -> dict:
        """Record where work stands so the next session can resume. Do this after meaningful work.
        task defaults to this session's task. The records the checkpoint names (DEC-004, BUG-2,
        a file with notes) are linked to its task, so the next pack for that task finds them."""
        found, _ = pick(session, project, write=True)
        if task is None and (current := working.current(session, found.id)) is not None:
            task = current.id
        cp = CheckpointService(session).create(
            found.id,
            CheckpointCreate(
                title=title,
                summary=summary,
                completed_work=completed_work,
                remaining_work=remaining_work,
                problems=problems,
                next_steps=next_steps,
                task_id=task,
                agent=agent,
                git_commit=git_commit,
            ),
            actor_type=actor,
            actor_name=agent,
        )
        if cp.task_id:
            working.set(found.id, cp.task_id)
        anchor = cp.task.human_id if cp.task else "this checkpoint"
        return {
            "created": cp.id,
            "title": cp.title,
            "task": cp.task.human_id if cp.task else None,
            "links": [
                f"{anchor} references {label}"
                for label in discover_checkpoint_quietly(session, found.id, cp.id, agent)
            ],
        }

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
        being asked. shelf files it on the shelf of knowledge it belongs to (a name or path,
        project shelf or shared tree); without one, a likely shelf is suggested. related names records it relates to (DEC-003, a task, file:src/a.gd); tasks
        names the tasks it applies to; links adds typed links, each written "relationship
        target" ("caused_by DEC-002", "resolved_by PROJ-6"). Without tasks, it is linked to this
        session's task. Records its text names are linked too. A name that matches nothing is
        reported in not_linked, and the memory is still saved. Agent-created memory is unlocked
        and marked as agent-written. An idea is never a requirement. project="global" is for
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
        return {
            "created": created.human_id,
            "type": created.type,
            "title": created.title,
            "linked_to": [r.human_id for r in created.related],
            "tasks": [t.human_id for t in created.tasks],
            **file_on_shelf(session, found.id, created.id, f"{title} {content}", shelf),
            **link_written(
                session,
                found.id,
                f"memory:{created.id}",
                actor=agent,
                links=[*named.links, *(links or [])],
                session_task=None if created.tasks else working.current(session, found.id),
                not_linked=named.not_linked,
            ),
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
        return {
            "shared_tree": [
                {"shelf": service.path(s), "records": len(members.get(s.id, ())), "keywords": k}
                for s in shelves
                for k in [[w for w in s.keywords.split(",") if w]]
            ],
            "project_shelves": [
                {
                    "shelf": service.path(service.get(found.id, s.id)),
                    "keywords": s.keywords,
                    "records": s.member_count,
                }
                for s in own
            ],
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
        complete_task, update_task, add_acceptance_criterion, associate_file, or create_bug. Use this for
        locked memory and for completing tasks. Nothing changes until it is accepted."""
        found, _ = pick(session, project, write=True)
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

    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="project-moah-mcp", description="Project Moah MCP server (stdio)"
    )
    parser.add_argument(
        "--agent", default="agent", help="who is connecting: codex, claude, or another name"
    )
    parser.add_argument(
        "--project", default=None, help="project slug, name or id to use when none is given"
    )
    parser.add_argument(
        "--brief",
        action="store_true",
        help="print the session brief for --cwd and exit (for agent start-up hooks)",
    )
    parser.add_argument("--cwd", default=None, help="working folder used to find the project")
    args = parser.parse_args(argv)
    url = get_database_url()
    upgrade_database(url)
    engine = make_engine(url)
    if args.brief:
        try:
            with make_session_factory(engine)() as session:
                sync_quietly(session)
                try:
                    found, _ = resolve_project(session, args.project, args.cwd)
                    note = None
                except ProjectChoiceError as error:
                    found, note = None, str(error)
                print(build_brief(session, found, note), flush=True)
        finally:
            engine.dispose()
        return 0
    try:
        # stdout belongs to the protocol; anything human-readable goes to stderr.
        print(f"Project Moah MCP server ready (agent: {args.agent})", file=sys.stderr, flush=True)
        build_server(
            make_session_factory(engine), agent=args.agent, default_project=args.project
        ).run("stdio")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Reading records: tasks, their pictures and related work, search, changed files."""

from __future__ import annotations

import base64
from typing import Any

from mcp.types import ImageContent, TextContent
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException

from app.mcp.hints import ANY_WORD_LIMIT, ANY_WORD_NOTE, NEAR_MISS, near_misses
from app.mcp.kit import READ, ToolKit
from app.mcp.reviews import review_for_agent
from app.models.memory import Memory
from app.models.project import GLOBAL_PROJECT_ID
from app.models.task import Task
from app.services.checkpoints import CheckpointService
from app.services.files import FileService
from app.services.graph import GraphService
from app.services.images import ImageService
from app.services.memory import MemoryService
from app.services.reviews import ReviewService
from app.services.search import SearchService
from app.services.tasks import TaskService


def register(kit: ToolKit) -> None:
    tool = kit.tool
    pick = kit.pick

    @tool(READ)
    def brain_get_task(session: Session, task: str, project: str | None = None) -> dict:
        """Full detail for one task: description, acceptance criteria, relationships, and milestone."""
        found, _ = pick(session, project)
        detail = TaskService(session).detail(found.id, task)
        return {**detail.model_dump(mode="json"), **review_for_agent(session, detail.id)}

    @tool(READ)
    def brain_view_images(session: Session, record: str, project: str | None = None) -> list:
        """See the images a person attached to a task or memory record (PROJ-6, DEC-3, or one
        image's id). Records that have images list them under images; this returns the pictures
        themselves, so look at them before working from the record. For a task sent back from
        review, it also shows the pictures the person attached to their comment."""
        found, _ = pick(session, project)
        reviews = ReviewService(session)
        attached = reviews.find_file(record.strip())
        if attached is not None and attached.project_id in (found.id, GLOBAL_PROJECT_ID):
            if attached.media_type == "text/plain":
                return [TextContent(type="text", text=attached.data.decode("utf-8", "replace"))]
            return [
                TextContent(type="text", text=f"{attached.filename} ({attached.media_type})"),
                ImageContent(
                    type="image",
                    data=base64.b64encode(attached.data).decode(),
                    mime_type=attached.media_type,
                ),
            ]
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
        if one is None and kind == "task":
            latest = reviews.latest(owner_id)
            if latest is not None and latest.status == "rejected":
                images += [
                    f for f in reviews.feedback_files(latest.id) if f.media_type != "text/plain"
                ]
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
        status: list[str] | str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """List tasks compactly. status can be backlog, todo, in_progress, blocked, review, completed."""
        found, _ = pick(session, project)
        if isinstance(status, str):  # one status, as the agent naturally writes it
            status = [part.strip() for part in status.split(",") if part.strip()]
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
        """Search tasks, memory, checkpoints and files. A plain question works: when no record has
        every word, records with any of them are returned, best first. scope is 'project'
        (default) or 'all'; results from all projects are for reading only and must not be
        treated as this project's truth."""
        search = SearchService(session)
        options: dict[str, Any] = {
            "entity_types": types,
            "for_agent": True,
            "limit": max(1, min(limit, 50)),
        }
        if scope == "project":
            options["project_id"] = pick(session, project)[0].id
        elif scope != "all":
            raise ValueError("scope must be 'project' or 'all'")
        result = search.search(query, **options)
        loose = False
        if not result["total"]:
            # Agents type questions, not keywords: "which day does the week start" has no
            # record with every word, but "Weeks start on Monday" shares some of them. Checking
            # before asking the person must stay cheaper than a pack: the best few only.
            options["limit"] = min(options["limit"], ANY_WORD_LIMIT)
            result = search.search(query, any_word=True, **options)
            loose = bool(result["total"])
        # In one project the project's name says nothing; loose matches skip status too.
        keys = ["entity_type", "human_id", "title", "snippet"]
        keys += [] if loose else ["status"]
        keys += ["project_name"] if scope == "all" else []
        rows = [{k: h[k] for k in keys} for h in result["items"]]
        total = result["total"]
        if not loose and 0 < total < ANY_WORD_LIMIT:
            # One weak record with every word (a checkpoint quoting the query) must not hide
            # the decision that has all but one of them: "offline gold cap" finds "Offline gold
            # started" and "Offline gains: at most 8 hours" ("offline", "gold" in its text).
            extra = near_misses(search, query, result["items"], options, ANY_WORD_LIMIT - total)
            rows += [
                {**{k: h[k] for k in keys if k != "status"}, "match": NEAR_MISS} for h in extra
            ]
            total += len(extra)
        return {
            **({"matched": ANY_WORD_NOTE} if loose else {}),
            "total": total,
            "results": rows,
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

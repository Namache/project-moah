"""Creating, updating and archiving tasks, and archiving memory."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException

from app.mcp.hints import possible_duplicate_tasks
from app.mcp.kit import WRITE, ToolKit
from app.mcp.linking import link_written
from app.mcp.reviews import REVIEW_DRAFTED
from app.models.checkpoint import ActivityEvent
from app.schemas.proposal import ProposalCreate
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.memory import MemoryService
from app.services.proposals import ProposalService
from app.services.reviews import ReviewService
from app.services.tasks import TaskService

NEW_TASK_STATUSES = ("in_progress", "todo", "backlog")

ASK_HINT = (
    "Not asked yet: if you need the person's answer to go on, now call "
    'brain_ask_person(task="{task}", question, options). The question waits in Project Moah\'s '
    "Review screen until they answer; a chat reply may never reach them."
)

ARCHIVE_LIMIT = 200  # tasks one brain_archive_tasks call may change

# Where a restored task goes, by the column it was archived from. Review and Blocked wait on
# a report or a question that archiving settled, so those come back as To do.
RESTORE_TO = {"completed": "completed", "backlog": "backlog"}


def status_before_archive(session: Session, task_id: str) -> str:
    """The column a task goes back to when restored from the archive."""
    event = session.scalar(
        select(ActivityEvent)
        .where(ActivityEvent.task_id == task_id, ActivityEvent.event_type == "TASK_ARCHIVED")
        .order_by(ActivityEvent.timestamp.desc())
        .limit(1)
    )
    previous = (event.metadata_json or {}).get("previous_status") if event else None
    return RESTORE_TO.get(previous or "", "todo")


def register(kit: ToolKit) -> None:
    tool = kit.tool
    pick = kit.pick
    agent = kit.agent
    working = kit.working
    file_on_shelf = kit.file_on_shelf

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
        """Create a task. status: in_progress for the request you start on now (it becomes
        this session's task, so your notes and checkpoints land on it), todo or backlog for
        later work. People decide when work is complete. links adds typed links, each written
        "relationship target" ("caused_by BUG-002"). A task created while this session works
        on another task is linked to that task."""
        found, _ = pick(session, project, write=True)
        if status not in NEW_TASK_STATUSES:
            raise ValueError(
                "A new task starts as 'in_progress' (work you start now), 'todo' or 'backlog'."
            )
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
        linked = link_written(
            session,
            found.id,
            f"task:{task.id}",
            actor=agent,
            links=links or [],
            session_task=working.current(session, found.id),
        )
        if task.status == "in_progress":
            working.set(found.id, task.id)
        return {
            "created": task.human_id,
            "title": task.title,
            "status": task.status,
            **file_on_shelf(
                session, found.id, task.id, f"{title} {description or ''}", None, kind="task"
            ),
            **linked,
            **possible_duplicate_tasks(session, found.id, task.id, task.title),
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
        """Update a task's working fields. A finished task goes to the person's review: hand it
        over with brain_submit_review, which writes your report and moves it to review (status
        completed or review alone moves it there with a report Moah drafts from your
        checkpoints). Archiving becomes a proposal. Setting status in_progress makes it this
        session's task. links adds typed links, each written "relationship target"
        ("blocked_by PROJ-4")."""
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
        drafted = False
        if status in ("completed", "review"):
            # People decide when work is complete: a finished task waits in review.
            current = TaskService(session).get(found.id, task)
            if current.status in ("completed", "archived"):
                raise ValueError(
                    f"{current.human_id} is already {current.status}. Nothing changed."
                )
            drafted = ReviewService(session).submitted_review(current.id) is None
            changes["status"] = status = "review"
        if changes:  # links alone change no field: nothing to check
            TaskUpdate.model_validate(changes)
        proposals = ProposalService(session)
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
        result = {
            "applied": True,
            "task": updated.human_id,
            "status": updated.status,
            **link_written(session, found.id, f"task:{updated.id}", actor=agent, links=links or []),
        }
        if drafted:
            result["next"] = REVIEW_DRAFTED.format(task=updated.human_id)
        if status == "blocked" and ReviewService(session).asked_question(updated.id) is None:
            result["next"] = ASK_HINT.format(task=updated.human_id)
        return result

    @tool(WRITE)
    def brain_archive_tasks(
        session: Session,
        person_asked: str,
        tasks: list[str] | None = None,
        all_done: bool = False,
        restore: bool = False,
        project: str | None = None,
    ) -> dict:
        """Archive tasks, but ONLY when the person asked you to in this conversation: never on
        your own initiative, never to tidy up. Archived tasks leave the board and the brief but
        keep their history, and can be restored. person_asked: the person's own words asking
        for it, kept in each task's history. tasks: task IDs to archive. all_done: true
        archives every Done task of the project. restore: true takes the named tasks out of the
        archive instead (a Done task goes back to Done, any other to To do). Want to archive
        something the person did not ask for? Suggest it with brain_create_proposal."""
        asked = person_asked.strip()
        if len(asked) < 3:
            raise ValueError(
                "person_asked must quote the person's request. Archive only when they asked; "
                "otherwise suggest it with brain_create_proposal."
            )
        if restore and all_done:
            raise ValueError("Restore names its tasks: give tasks, not all_done.")
        if not tasks and not all_done:
            raise ValueError("Name the tasks, or set all_done to archive every Done task.")
        found, _ = pick(session, project, write=True)
        service = TaskService(session)
        refs = list(dict.fromkeys(tasks or []))
        if all_done:
            refs += [
                t.human_id
                for t in service.list(found.id, statuses=["completed"])
                if t.human_id not in refs
            ]
        if len(refs) > ARCHIVE_LIMIT:
            raise ValueError(f"At most {ARCHIVE_LIMIT} tasks at a time; got {len(refs)}.")
        note = {"asked_by_person": asked[:500], "by_agent_on_request": True}
        changed: list[dict] = []
        skipped: list[dict] = []
        for ref in refs:
            try:
                row = service.get(found.id, ref)
            except HTTPException:
                skipped.append({"task": ref, "why": "not found in this project"})
                continue
            if restore:
                if row.status != "archived":
                    skipped.append({"task": row.human_id, "why": f"not archived ({row.status})"})
                    continue
                back = status_before_archive(session, row.id)
                service.update(found.id, row.id, TaskUpdate(status=back), note)
                changed.append({"task": row.human_id, "title": row.title, "status": back})
            else:
                if row.status == "archived":
                    skipped.append({"task": row.human_id, "why": "already archived"})
                    continue
                was = row.status
                service.update(found.id, row.id, TaskUpdate(status="archived"), note)
                changed.append({"task": row.human_id, "title": row.title, "was": was})
        verb = "restored" if restore else "archived"
        result: dict = {verb: changed, "count": len(changed)}
        if skipped:
            result["skipped"] = skipped
        if not changed:
            result["message"] = f"Nothing {verb}."
        elif restore:
            result["message"] = "Tell the person which tasks are back on the board."
        else:
            result["message"] = (
                "Tell the person what you archived. They can restore a task from its details "
                "in Project Moah, or ask you: brain_archive_tasks(tasks=[...], restore=true, "
                'person_asked="...").'
            )
        return result

    @tool(WRITE)
    def brain_archive_memories(
        session: Session,
        person_asked: str,
        memories: list[str],
        restore: bool = False,
        project: str | None = None,
    ) -> dict:
        """Archive rules, decisions and other memory records, but ONLY when the person asked
        you to in this conversation: never on your own initiative, never to tidy up. Archived
        records leave the brief and context packs but keep their history, and can be restored.
        person_asked: the person's own words asking for it, kept in each record's history.
        memories: record IDs (RULE-015, DEC-004); project="global" for Global rules. restore:
        true brings archived records back. Locked records stay the person's: suggest those
        with brain_create_proposal, like anything the person did not ask for."""
        asked = person_asked.strip()
        if len(asked) < 3:
            raise ValueError(
                "person_asked must quote the person's request. Archive only when they asked; "
                "otherwise suggest it with brain_create_proposal."
            )
        refs = list(dict.fromkeys(memories))
        if not refs:
            raise ValueError("Name the records to archive.")
        if len(refs) > ARCHIVE_LIMIT:
            raise ValueError(f"At most {ARCHIVE_LIMIT} records at a time; got {len(refs)}.")
        found, _ = pick(session, project, write=True)
        service = MemoryService(session)
        note = {"asked_by_person": asked[:500], "by_agent_on_request": True}
        changed: list[dict] = []
        skipped: list[dict] = []
        for ref in refs:
            try:
                row = service.get(found.id, ref)
            except HTTPException:
                skipped.append({"memory": ref, "why": "not found in this project"})
                continue
            if row.is_locked:
                skipped.append(
                    {"memory": row.human_id, "why": "locked: only the person can change it"}
                )
                continue
            wanted = ("archived", "invalidated") if restore else ("active",)
            if row.status not in wanted:
                skipped.append({"memory": row.human_id, "why": f"it is {row.status}"})
                continue
            if restore:
                service.restore(found.id, row.id, actor=agent, note=note)
            else:
                service.archive(found.id, row.id, actor=agent, note=note)
            changed.append({"memory": row.human_id, "type": row.type, "title": row.title})
        verb = "restored" if restore else "archived"
        result: dict = {verb: changed, "count": len(changed)}
        if skipped:
            result["skipped"] = skipped
        result["message"] = (
            f"Nothing {verb}."
            if not changed
            else f"Tell the person what you {verb}."
            + (
                ""
                if restore
                else " They can restore a record from its details in Project Moah, or ask you "
                "(restore=true)."
            )
        )
        return result

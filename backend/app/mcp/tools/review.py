"""Handing work to the person: questions, reviews and checkpoints."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.mcp.kit import WRITE, ToolKit
from app.mcp.reviews import (
    clear_dropped,
    read_screenshots,
    review_drop_folder,
    review_drop_folder_for,
)
from app.models.project import GLOBAL_PROJECT_ID
from app.models.task import Task
from app.schemas.checkpoint import CheckpointCreate
from app.schemas.review import AskPerson, ReviewSubmit
from app.schemas.task import TaskCreate
from app.services.brief import checkpoint_task, headline_tasks
from app.services.checkpoints import CheckpointService
from app.services.discovery import discover_checkpoint_quietly
from app.services.retrieval import RetrievalService
from app.services.review_waits import waits_on_person
from app.services.reviews import CLOSED, STARTED_TAG, ReviewService
from app.services.tasks import TaskService

# A task Moah starts for work an agent did without one, once that work waits for the person.
STARTED_BY_MOAH = (
    "Started by Project Moah: an agent worked without a task and stopped to wait for you. "
    "Rename it, merge it into the task it belongs to, or archive it if it was nothing."
)

TASK_TITLE_LIMIT = 200

# Said when an agent waits on a task the person already closed (ReviewService.follow_up).
FOLLOW_UP_NOTE = (
    "{closed} is already closed, so this waits in {task}, the follow-up Moah keeps for it. Go "
    "on in {task}; this session's next notes land there."
)


def register(kit: ToolKit) -> None:
    tool = kit.tool
    pick = kit.pick
    agent = kit.agent
    actor = kit.actor
    working = kit.working
    packs = kit.packs
    session_factory = kit.session_factory

    @tool(WRITE)
    def brain_ask_person(
        session: Session,
        task: str,
        question: str,
        context: str | None = None,
        options: list[str] | None = None,
        project: str | None = None,
    ) -> dict:
        """Ask the person something only they can answer when you cannot go on without it: a
        choice, a fact, an approval. Use it whenever you stop to ask, also when you ask in the
        chat: a chat question is easily lost, this one waits in Project Moah's Review screen
        until they answer. Check Moah first (brain_search): they may have answered before. The
        task moves to Blocked; the answer then shows in the brief and brain_get_task, and the
        task is in progress again. question: one or two plain sentences (several questions can
        go in one). context: optional Markdown on what you found and what each choice would
        mean. options: up to 6 short answers to pick from. Then stop; don't guess the answer."""
        found, _ = pick(session, project, write=True)
        payload = AskPerson(question=question, context=context, options=options or [])
        about = TaskService(session).get(found.id, task)
        closed = about.human_id if about.status in CLOSED else None
        review = ReviewService(session).ask(found.id, about.id, payload, agent)
        row = session.get(Task, review.task_id)
        working.set(found.id, row.id)
        result = {
            "asked": row.human_id,
            "status": row.status,
            "message": "It waits in the person's Review screen. Stop work on this task and tell "
            "them you asked; the brief shows their answer when it comes.",
        }
        if closed is not None and row.human_id != closed:
            result["task_started"] = FOLLOW_UP_NOTE.format(closed=closed, task=row.human_id)
        return result

    def brain_submit_review(
        session: Session,
        task: str,
        summary: str,
        done: list[str],
        not_done: list[str] | None = None,
        how_to_check: str | None = None,
        details: str | None = None,
        screenshots: list[str] | None = None,
        captions: list[str] | None = None,
        project: str | None = None,
    ) -> dict:
        """Hand a finished task to the person for review; it moves to status review and waits
        in Project Moah's Review screen until they accept it or send it back with comments.
        summary: two or three plain sentences on what changed for them. done: each thing
        finished, one short line each. not_done: what is left, skipped, failed or unverified
        (be honest; an empty list says everything was done). how_to_check: steps the person
        can follow to see it working. details: optional Markdown for anything else (tables,
        code, notes; "> [!WARNING]" makes a warning box). screenshots: image file paths (PNG,
        JPEG, WebP or GIF, up to 10, 5 MB each), with captions in the same order. Attach
        screenshots whenever the result is something the person can see (a screen, a page, a
        chart, a document, a game scene): take them with the tools you have, for example
        Playwright or a screenshot command. Submitting again replaces a review still waiting.
        After a send-back, brain_get_task shows the person's comment."""
        found, _ = pick(session, project, write=True)
        payload = ReviewSubmit(
            summary=summary,
            done=done,
            not_done=not_done or [],
            how_to_check=how_to_check,
            details=details,
        )
        drop = review_drop_folder(session)
        shots = read_screenshots(screenshots or [], captions, drop)
        review = ReviewService(session).submit(found.id, task, payload, agent, shots)
        clear_dropped(screenshots or [], drop)
        row = session.get(Task, review.task_id)
        working.set(found.id, row.id)
        result = {
            "submitted": row.human_id,
            "round": review.round,
            "status": row.status,
            "screenshots": len(shots),
            "message": "It waits in the person's Review screen. Don't keep working on it unless "
            "they send it back; the brief and brain_get_task then show their comment.",
        }
        if not shots:
            result["note"] = (
                "No screenshots attached. If the person can see the result, submit again with "
                "screenshots."
            )
        return result

    if (drop := review_drop_folder_for(session_factory)) is not None:
        brain_submit_review.__doc__ += (
            f" On this computer Project Moah runs in a sandbox: save screenshots in {drop}"
            " and pass those paths."
        )
    tool(WRITE)(brain_submit_review)

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
        waiting_for_person: bool | None = None,
    ) -> dict:
        """Record where work stands so the next session can resume: after task work, before
        your final reply. task defaults to this session's task, else to the brief's unfinished
        task if the checkpoint names it or its records. Records it names (DEC-004, BUG-2, a file
        with notes) are linked to its task. Records your packs held that summary,
        completed_work or next_steps name count as useful feedback. waiting_for_person: true
        when you stop for the person's OK, pick or answer (a plan, a mockup, a commit): the
        title then waits in their Review screen as your question, and your next checkpoint
        settles it."""
        found, _ = pick(session, project, write=True)
        guessed = moved = None
        current = working.current(session, found.id) if task is None else None
        if task is None:
            # A note about another task belongs to it, not to the one the session last touched:
            # "IDLE-006 popup laid out" while the session's task is IDLE-005. Only when the
            # note's headline (its title, or the ref opening its summary) names exactly one
            # task, not as an aside ("unblocked by IDLE-005"), and not the session's own.
            named = headline_tasks(session, found, title, summary)
            if len(named) == 1 and (current is None or named[0].id != current.id):
                moved = named[0]
                task = moved.id
        if task is None and current is not None:
            task = current.id
        elif task is None:
            # Worked from the brief alone, with no pack: the brief's unfinished task, when the
            # checkpoint is about it, so the next brief does not show its old "Left to do".
            texts = [title, summary, completed_work, remaining_work, problems, next_steps]
            guessed = checkpoint_task(session, found, texts)
            task = guessed.id if guessed is not None else None
        waits = waits_on_person(title, waiting_for_person)
        started = followed = None
        if waits and task is not None:
            about = TaskService(session).get(found.id, task)
            if about.status in CLOSED:
                # The person already accepted (or archived) it: the wait goes to its follow-up.
                row, _ = ReviewService(session).follow_up(about, agent)
                followed, task = (about.human_id, row.human_id), row.id
        if waits and task is None and found.id != GLOBAL_PROJECT_ID:
            # Work that waits for the person needs a task to wait in Review with. The session
            # keeps it, so its later notes land on it too: one task per session, not per note.
            started = TaskService(session).create(
                found.id,
                TaskCreate(
                    title=" ".join(title.split())[:TASK_TITLE_LIMIT] or "Work waiting for you",
                    description=STARTED_BY_MOAH,
                    status="in_progress",
                    tags=[STARTED_TAG],
                ),
            )
            task = started.id
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
        reviews, row = ReviewService(session), session.get(Task, cp.task_id) if cp.task_id else None
        waiting = reviews.wait_from_checkpoint(row, cp, agent) if waits and row else None
        if row is not None and not waits:
            reviews.moved_on(row)
        anchor = cp.task.human_id if cp.task else "this checkpoint"
        result = {
            "created": cp.id,
            "title": cp.title,
            "task": cp.task.human_id if cp.task else None,
            "links": [
                f"{anchor} references {label}"
                for label in discover_checkpoint_quietly(session, found.id, cp.id, agent)
            ],
        }
        if followed is not None:
            result["task_started"] = FOLLOW_UP_NOTE.format(closed=followed[0], task=followed[1])
        if started is not None:
            result["task_started"] = (
                f"No task was set, so Moah started {started.human_id} for this work. Pass "
                "task= next time if it belongs to another one."
            )
        if waiting is not None:
            result["review"] = (
                f"{cp.task.human_id} waits for the person in their Review screen. Stop and ask "
                "them; when you go on, your next checkpoint settles it."
            )
        if moved is not None:
            result["task_note"] = (
                f"Filed under {moved.human_id}, the task this checkpoint names"
                + (f", not this session's task {current.human_id}" if current else "")
                + f". {moved.human_id} is now this session's task; pass task= for another."
            )
        if guessed is not None:
            result["task_note"] = (
                f"{guessed.human_id} is the unfinished task in your brief and this checkpoint "
                "names it or its records. Pass task= for another."
            )
        # What the work used, in the agent's own words: records of this session's packs it
        # names as done or as the next step (not its problems) helped, unless it already said.
        helped = RetrievalService(session).feedback_from_checkpoint(
            found.id,
            packs.get(session, found.id).retrievals,
            [summary, completed_work, next_steps],
            actor=agent,
        )
        if helped:
            result["feedback"] = "; ".join(
                f"counted as feedback for {short}: {', '.join(ids)}" for short, ids in helped
            )
        return result

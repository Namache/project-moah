"""Starting a session: the brief, a second opinion, the projects and where one stands."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.mcp.cli import with_update_check
from app.mcp.kit import READ, ToolKit
from app.mcp.projects import ProjectChoiceError
from app.services.agent_prompts import second_opinion
from app.services.agent_sync import sync_quietly
from app.services.brief import build_brief
from app.services.checkpoints import CheckpointService
from app.services.files import FileService
from app.services.projects import ProjectService
from app.services.proposals import ProposalService
from app.services.settings import get_agent_settings
from app.services.tasks import TaskService
from app.services.update_check import install_steps


def register(kit: ToolKit) -> None:
    tool = kit.tool
    pick = kit.pick
    agent = kit.agent
    working = kit.working
    packs = kit.packs
    briefed = kit.briefed
    session_task = kit.session_task

    @tool(READ)
    def brain_brief(
        session: Session,
        cwd: str | None = None,
        project: str | None = None,
        update_steps: bool = False,
    ) -> str:
        """Start here, once per session. Returns the person's global rules, the project's rules,
        the unfinished task with what is already decided for it, the latest checkpoint, and how
        to keep Project Moah current. Pass your working folder as cwd. Works outside any project
        too: then only global rules apply. update_steps=true returns only the steps to install a
        Project Moah update on this system, once the person said yes to one."""
        if update_steps:
            return install_steps()  # mid-session: the session and its packs stay as they are
        working.clear()  # a new session starts with no task of its own
        packs.clear()  # and has been sent nothing yet
        sync_quietly(session)  # a folder first seen in this session gets its project now
        try:
            found, _ = pick(session, project, cwd)
            note = hint = None
        except ProjectChoiceError as error:
            found, note, hint = None, str(error), error.hint
        briefed["project"] = found.id if found is not None and found.kind != "global" else None
        return with_update_check(session, build_brief(session, found, note, hint))

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

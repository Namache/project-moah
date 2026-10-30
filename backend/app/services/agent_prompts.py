"""Prompts Project Moah writes for agents: "Work on task" and second opinions.

Nothing here runs an agent. "Work on task" opens the person's desktop app with the prompt typed in
but not sent; a second opinion is a read-only command the asking agent runs in its own terminal,
where the person sees and approves it.
"""

from __future__ import annotations

import shlex
from urllib.parse import quote

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.project import Project
from app.services.context import ContextService
from app.services.settings import AgentName, AgentSettings
from app.services.tasks import TaskService
from app.services.usage import normalize_folder

# Both desktop apps' links accept a few thousand characters; Claude Code's deep links take 5,000.
PROMPT_LIMIT = 4500
DESCRIPTION_LIMIT = 1500
NAMES: dict[str, str] = {"claude": "Claude", "codex": "Codex"}
HEREDOC = "PB_SECOND_OPINION"


def _folder(project: Project, cwd: str | None = None) -> str | None:
    if project.root_path:
        return normalize_folder(project.root_path)
    return normalize_folder(cwd) if cwd else None


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _task_block(session: Session, project: Project, task_ref: str) -> tuple[str, str]:
    task = TaskService(session).detail(project.id, task_ref)
    lines = [f"{task.human_id} {task.title} (status: {task.status.replace('_', ' ')})"]
    if task.description:
        lines += ["", _clip(task.description, DESCRIPTION_LIMIT)]
    criteria = task.acceptance_criteria
    if criteria:
        lines += ["", "Acceptance criteria (all must be met):"]
        lines += [f"- [{'x' if c.is_completed else ' '}] {c.description}" for c in criteria]
    if task.next_action:
        lines += ["", f"Next action: {task.next_action}"]
    return task.human_id, "\n".join(lines)


def work_prompt(session: Session, project: Project, task_ref: str, agent: AgentName) -> dict:
    """A prompt that sets an agent up to complete one task well, and the link that opens it."""
    if project.kind != "project":
        raise HTTPException(status_code=409, detail="Tasks belong to projects.")
    human_id, task = _task_block(session, project, task_ref)
    folder = _folder(project)
    where = f"Project folder: {folder}" if folder else "The project has no folder set yet."
    prompt = f"""\
Work on task {human_id} in the Project Moah project "{project.name}" ({project.slug}).
{where}

Before you start
1. Call brain_context_pack with task="{human_id}" and project="{project.slug}", and read the files
   it names. Follow the global and project rules in your Project Moah brief.
2. If anything below is unclear, or the code disagrees with it, ask me before building.

The task
{task}

How to work
- Plan first: say what you will change and why, and follow the rules about asking before building.
- Make the smallest change that meets every acceptance criterion. Match the surrounding code.
- Verify: run the relevant tests and check each criterion. Report what was implemented, what was
  tested, what was verified by hand, and what is not verified yet.
- Record decisions and findings with brain_create_memory, linked to {human_id}.
- Finish with brain_create_checkpoint for {human_id}. Completing the task needs my review: propose
  it with brain_create_proposal (complete_task) instead of marking it done."""
    prompt = _clip(prompt, PROMPT_LIMIT)
    if agent == "codex":
        url = "codex://new?prompt=" + quote(prompt, safe="")
        if folder:
            url += "&path=" + quote(folder, safe="")
    else:
        # Claude's desktop link cannot choose a folder; the prompt names it.
        url = "claude://code/new?q=" + quote(prompt, safe="")
    return {"agent": agent, "task": human_id, "prompt": prompt, "url": url, "folder": folder}


def second_opinion(
    session: Session,
    settings: AgentSettings,
    project: Project,
    asking: str,
    question: str,
    task_ref: str | None = None,
    cwd: str | None = None,
) -> dict:
    """The read-only command that asks the other agent, and what to do with its answer."""
    if not settings.second_opinion_enabled:
        raise ValueError(
            "Second opinions are switched off. The person can switch them on in Project Moah: "
            "Settings, Agents."
        )
    asking = "codex" if asking.lower() == "codex" else "claude"
    other: AgentName = "claude" if asking == "codex" else "codex"
    blocks = [f"Question\n{question.strip()}"]
    human_id = None
    if project.kind == "project":
        if task_ref:
            human_id, task = _task_block(session, project, task_ref)
            blocks.append(f"Task\n{task}")
        pack = ContextService(session).build(
            project.id, task=human_id, query=question, detail="minimal", budget=1200
        )
        blocks.append(f"Project context from Project Moah\n{pack.text}")
    prompt = (
        f"You are giving a second opinion to {NAMES[asking]}, another coding agent working with "
        "me on the same project. Think independently; do not simply agree. Do not change any "
        "files. Read whatever you need.\n\n"
        + "\n\n".join(blocks)
        + "\n\nAnswer in under 400 words:\n1. Your recommendation.\n2. Where you disagree with the "
        "likely approach, or risks it misses.\n3. What you are unsure about."
    ).replace(HEREDOC, HEREDOC.lower())
    folder = _folder(project, cwd)
    if other == "codex":
        where = f" -C {shlex.quote(folder)}" if folder else ""
        command = (
            f"{settings.codex_command} exec --sandbox read-only --skip-git-repo-check --ephemeral"
            f"{where} - <<'{HEREDOC}'\n{prompt}\n{HEREDOC}"
        )
    else:
        enter = f"cd {shlex.quote(folder)} && " if folder else ""
        command = (
            f"{enter}{settings.claude_command} -p --permission-mode plan --allowedTools Read Grep "
            f"Glob --no-session-persistence <<'{HEREDOC}'\n{prompt}\n{HEREDOC}"
        )
    save = (
        f'brain_create_memory(type="note", title="Second opinion: <short topic>", '
        f'content=<both views>, tasks=["{human_id}"], project="{project.slug}")'
        if human_id
        else f'brain_create_memory(type="note", title="Second opinion: <short topic>", '
        f'content=<both views>, project="{project.slug}")'
    )
    return {
        "other_agent": other,
        "command": command,
        "instructions": (
            f"Run the command in your terminal; it is read-only and the person approves it there. "
            f"It may take a few minutes. Then show the person both views side by side: your own "
            f"answer first, then {NAMES[other]}'s, then where you agree and where you differ, and "
            f"your combined recommendation. Save both with {save}. If the command is not found, "
            "tell the person to set the command for "
            f"{NAMES[other]} in Project Moah: Settings, Agents."
        ),
    }

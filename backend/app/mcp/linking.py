"""How an agent's writes join the Brain.

Every record an agent writes through MCP is linked as it is saved, from three sources, most
trusted first:
- what the agent names with the write: ``related``, ``tasks``, and ``links`` written as
  "relationship target" ("caused_by DEC-002");
- what the text names (DEC-004, a file with notes, global RULE-3); see app.services.discovery;
- the task this session is working on: a record written without naming a task is linked to it,
  because it was written during that work.

One MCP server process serves one agent session, so the session's task is held here, in memory,
and is gone when the session ends. It is the task the agent last asked a context pack for, set in
progress, or wrote a checkpoint about. brain_brief starts a new session and clears it, and so does
a long pause, so a record written the next morning is not tied to last night's task.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.task import Task
from app.services.discovery import discover_quietly, link_to_task_quietly
from app.services.graph import GraphService

log = logging.getLogger(__name__)

# A pause this long between tool calls ends the working session.
IDLE_SECONDS = 2 * 60 * 60


class SessionTask:
    """The task this agent session is working on, per project."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._tasks: dict[str, str] = {}
        self._seen = clock()

    def tick(self) -> None:
        """Called on every tool call."""
        now = self._clock()
        if now - self._seen > IDLE_SECONDS:
            self._tasks.clear()
        self._seen = now

    def clear(self) -> None:
        self._tasks.clear()

    def set(self, project_id: str, task_id: str) -> None:
        self._tasks[project_id] = task_id

    def tasks(self) -> dict[str, str]:
        """Project id -> task id, for every project this session has a task in."""
        return dict(self._tasks)

    def current(self, session: Session, project_id: str) -> Task | None:
        """The session's task in this project. One deleted or archived since is forgotten."""
        task_id = self._tasks.get(project_id)
        if task_id is None:
            return None
        task = session.get(Task, task_id)
        if task is None or task.project_id != project_id or task.status == "archived":
            self._tasks.pop(project_id, None)
            return None
        return task


@dataclass
class Named:
    """The records a write's related and tasks lists name, sorted by where the link is kept."""

    memories: list[str] = field(default_factory=list)  # this project's memory: memory links
    tasks: list[str] = field(default_factory=list)  # this project's tasks: the record's tasks
    links: list[str] = field(default_factory=list)  # files, Global records...: typed links
    not_linked: list[str] = field(default_factory=list)


def sort_named(session: Session, project_id: str, refs: Iterable[str]) -> Named:
    """An agent may name any record in related or tasks: a task in related is one of the
    memory's tasks, a file or Global record becomes a relates_to link. A name that matches
    nothing is reported instead of failing the write, so the record is never lost to a typo."""
    graph = GraphService(session)
    named = Named()
    for ref in refs:
        text = " ".join(str(ref).split())
        if not text:
            continue
        try:
            node = graph.resolve(project_id, text)
            scope = "project"
        except HTTPException as error:
            try:
                node = graph.resolve(project_id, text, allow_global=True)
                scope = "global"
            except Exception:  # noqa: BLE001 - reported with the project's own reason
                named.not_linked.append(f"{text}: {error.detail}")
                continue
        if scope == "project" and node.kind == "memory":
            named.memories.append(text)
        elif scope == "project" and node.kind == "task":
            named.tasks.append(text)
        else:
            named.links.append(f"relates_to {text}")
    return named


def link_written(
    session: Session,
    project_id: str,
    ref: str,
    *,
    actor: str,
    links: Iterable[str] = (),
    session_task: Task | None = None,
    not_linked: Iterable[str] = (),
) -> dict:
    """Link a record just written: the links the agent named, what its text names, and the
    session's task (pass it only when the record names no task of its own). Never fails: the
    record is saved already, and whatever could not be linked is reported in not_linked."""
    graph = GraphService(session)
    task_id = session_task.id if session_task is not None else None
    made: list[str] = []
    skipped = list(not_linked)
    links = [spec for spec in links if str(spec).strip()]
    if links:
        try:
            done, refused = graph.link_many(project_id, ref, links, actor=actor)
        except Exception as error:  # noqa: BLE001 - logged; the record stays saved
            session.rollback()
            log.exception("Saving the links named with %s failed", ref)
            done, refused = [], [f"{spec}: {type(error).__name__}" for spec in links]
        made += done
        skipped += refused
    found = discover_quietly(session, project_id, ref, actor)
    if task_id is not None:
        label = link_to_task_quietly(session, project_id, ref, task_id, actor)
        if label:
            made.append(f"relates_to {label} (this session's task)")
    return {
        "links": made,
        "references_found": found["mentions"],
        "possible_links": found["candidates"],
        "not_linked": skipped,
    }

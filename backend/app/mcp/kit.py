"""What every tool module gets from build_server: the tool decorator and this session's state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mcp.types import ToolAnnotations
from sqlalchemy.orm import Session, sessionmaker

from app.mcp.linking import SessionPacks, SessionTask

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
)


@dataclass(frozen=True)
class ToolKit:
    """build_server's helpers and the state one server keeps for its agent session (see
    build_server for what each does)."""

    tool: Callable[[ToolAnnotations], Callable[[Callable[..., Any]], Any]]
    pick: Callable[..., Any]
    agent: str
    actor: str
    working: SessionTask
    packs: SessionPacks
    briefed: dict[str, str | None]
    session_task: Callable[[Session, str], str | None]
    in_brief: Callable[[Session, str], bool]
    file_on_shelf: Callable[..., dict]
    session_factory: sessionmaker[Session]

"""App-wide settings shared by the app and the MCP server."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.app_setting import AppSetting

AgentName = Literal["claude", "codex"]


class AgentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Which desktop app "Work on task" opens.
    default_agent: AgentName = "claude"
    # Off by default: a second opinion uses the other agent's usage, and runs only when asked for.
    second_opinion_enabled: bool = False
    # How an agent starts the other one from its own terminal. Commands, not shell snippets:
    # Project Moah adds the read-only options and the prompt.
    codex_command: str = Field(default="codex", min_length=1, max_length=500)
    claude_command: str = Field(default="claude", min_length=1, max_length=500)
    # On by default: once a day the agent looks up the latest release with its own tools and asks
    # before updating. Project Moah itself never goes online either way.
    update_check_enabled: bool = True


class AgentSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_agent: AgentName | None = None
    second_opinion_enabled: bool | None = None
    codex_command: str | None = Field(default=None, min_length=1, max_length=500)
    claude_command: str | None = Field(default=None, min_length=1, max_length=500)
    update_check_enabled: bool | None = None


def get_agent_settings(session: Session) -> AgentSettings:
    stored = {row.key: row.value for row in session.scalars(select(AppSetting))}
    known = {k: v for k, v in stored.items() if k in AgentSettings.model_fields}
    try:
        return AgentSettings(**known)
    except ValueError:
        return AgentSettings()


def update_agent_settings(session: Session, changes: AgentSettingsUpdate) -> AgentSettings:
    now = datetime.now(UTC)
    for key, value in changes.model_dump(exclude_unset=True, exclude_none=True).items():
        if isinstance(value, str):
            value = value.strip()
        row = session.get(AppSetting, key) or AppSetting(key=key)
        row.value, row.updated_at = value, now
        session.add(row)
    session.commit()
    return get_agent_settings(session)


# ---- tasks ------------------------------------------------------------------------------

AUTO_DELETE_DONE = "auto_delete_done_tasks"


class TaskSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Off by default. When on, a task that has been Done for two weeks is deleted; its
    # activity entries stay. The clock starts when the task entered Done, or when the
    # setting was turned on if that is later, so nothing vanishes the day it is switched on.
    auto_delete_done: bool = False
    auto_delete_done_since: datetime | None = None


class TaskSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_delete_done: bool


def get_task_settings(session: Session) -> TaskSettings:
    row = session.get(AppSetting, AUTO_DELETE_DONE)
    if row is None or row.value is not True:
        return TaskSettings()
    since = row.updated_at
    if since is not None and since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    return TaskSettings(auto_delete_done=True, auto_delete_done_since=since)


def update_task_settings(session: Session, changes: TaskSettingsUpdate) -> TaskSettings:
    row = session.get(AppSetting, AUTO_DELETE_DONE) or AppSetting(key=AUTO_DELETE_DONE)
    # Only a real change restarts the clock: saving "on" again keeps when it was turned on.
    if row.value is not changes.auto_delete_done:
        row.value, row.updated_at = changes.auto_delete_done, datetime.now(UTC)
        session.add(row)
        session.commit()
    return get_task_settings(session)

"""Smaller tool schemas: every agent reads them, so every key costs tokens in every session.

The schemas FastMCP generates repeat a "title" for every argument ("Completed Work" for
completed_work) and spell each optional argument as anyOf [x, null] with a null default. Neither
helps an agent: the argument's name is its title, and an optional argument is simply left out.
Arguments are still checked against the tool's Python signature, so null still works.

The values an argument takes are listed, so an agent picks a valid one the first time instead
of learning it from an error.
"""

from __future__ import annotations

from typing import Any, get_args

from app.schemas.memory import Importance, MemoryType
from app.schemas.proposal import ProposalType
from app.schemas.task import TaskPriority, TaskStatus

NULL = {"type": "null"}

# tool -> argument -> allowed values.
CHOICES: dict[str, dict[str, list[str]]] = {
    "brain_create_task": {
        "status": ["in_progress", "todo", "backlog"],
        "priority": list(get_args(TaskPriority)),
    },
    "brain_update_task": {
        "status": list(get_args(TaskStatus)),
        "priority": list(get_args(TaskPriority)),
    },
    "brain_list_tasks": {"status": list(get_args(TaskStatus))},
    "brain_create_memory": {
        "type": list(get_args(MemoryType)),
        "importance": list(get_args(Importance)),
    },
    "brain_update_memory": {"importance": list(get_args(Importance))},
    "brain_create_proposal": {"proposal_type": list(get_args(ProposalType))},
}


def compact(schema: Any) -> Any:
    """``schema`` without argument titles and with optional arguments written plainly."""
    if isinstance(schema, list):
        return [compact(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    out = {key: compact(value) for key, value in schema.items() if key != "title"}
    if "properties" in schema:  # "title" may be an argument's name: keep the argument
        out["properties"] = {name: compact(value) for name, value in schema["properties"].items()}
    options = out.get("anyOf")
    if isinstance(options, list) and NULL in options:
        rest = [option for option in options if option != NULL]
        plain = {key: value for key, value in out.items() if key != "anyOf"}
        if plain.get("default", 0) is None:
            del plain["default"]
        if len(rest) == 1 and isinstance(rest[0], dict):
            out = {**rest[0], **plain}
        else:  # str | list[str] | None: the two real choices stay
            out = {"anyOf": rest, **plain}
    return out


def with_choices(tool: str, schema: dict) -> dict:
    for name, values in CHOICES.get(tool, {}).items():
        argument = schema.get("properties", {}).get(name)
        for shape in argument.get("anyOf", [argument]) if argument is not None else []:
            if shape.get("type") == "array":
                shape["items"] = {**shape.get("items", {}), "enum": values}
            elif shape.get("type") == "string":
                shape["enum"] = values
    return schema


def compact_tools(server: Any) -> None:
    """Rewrite every registered tool's schema in place. Only what clients are shown changes."""
    for tool in server._tool_manager.list_tools():
        tool.parameters = with_choices(tool.name, compact(tool.parameters))

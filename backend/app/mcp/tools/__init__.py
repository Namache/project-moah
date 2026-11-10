"""The MCP server's tools, by what they are for. Each module's ``register`` adds its tools to the
server, in the order agents see them."""

from __future__ import annotations

from app.mcp.kit import ToolKit
from app.mcp.tools import context, knowledge, records, review, start, tasks

GROUPS = (start, context, records, tasks, review, knowledge)


def register_all(kit: ToolKit) -> None:
    for group in GROUPS:
        group.register(kit)

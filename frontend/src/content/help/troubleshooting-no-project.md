---
title: Agent cannot see my project
category: Troubleshooting
summary: The agent says it cannot find or identify your project.
keywords: agent, project, not found, detect, missing
related: troubleshooting-mcp, review
---

## Problem

The agent says it cannot find or identify your project.

## Likely causes

- The MCP server is not connected, or was added before Project Moah was opened for the first time.
- The agent was started outside the project's folder, and no project was named.
- The project is archived, which agents can read but not change.

## How to fix

1. Run `claude mcp list` or `codex mcp list` and check the server shows as connected.
2. Start the agent in the project's folder or a subfolder. Project Moah finds the project from that folder, or makes one for it.
3. If the project has no folder yet, add it in the project settings, or name the project in your request.
4. Restore the project if it is archived.

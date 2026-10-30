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
- No project name was given and the working folder does not match any project's repository folder.
- The project is archived, which agents can read but not change.

## How to fix

1. Run `claude mcp list` or `codex mcp list` and check the server shows as connected.
2. Copy the setup command again from *Connect Claude Code* or *Connect Codex*, choosing your project, so it includes the project name.
3. Add the repository folder to the project, so it can be matched from the working directory.
4. Restore the project if it is archived.

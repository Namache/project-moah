---
title: MCP connection failed
category: Troubleshooting
summary: The agent cannot start or reach the Project Moah server.
keywords: mcp, connection, failed, server, flatpak, connect
related: troubleshooting-mcp, review
---

## Problem

The agent cannot start or reach the Project Moah server.

## Likely causes

- Project Moah is not installed, or was never opened.
- The setup command was changed or mistyped.
- The agent was not restarted after adding the server.
- The server was added with the wrong scope.

## How to fix

1. Check Project Moah is installed and has been opened once.
2. Run the setup command again, from the Connect guide.
3. Restart the agent, then run `claude mcp list` or `codex mcp list`.
{{only windows}}
1. If you reinstalled Project Moah in another folder, copy the setup commands again: they contain its location.
{{end}}
4. Project Moah itself keeps working even when the connection fails.

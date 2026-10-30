---
title: Connect Claude Code
category: Connect agents
summary: Set up Claude Code to use Project Moah.
keywords: claude, claude code, anthropic, mcp, connect, setup
related: troubleshooting-container, codex, troubleshooting-mcp, troubleshooting-no-project
---

Project Moah gives agents a local MCP server. It runs on your computer and needs no network.

## Steps

1. **Install and open Project Moah** once, so its data exists.
2. **Connect Claude Code once.** The same connection serves every project: Project Moah finds the project from the folder Claude Code works in, and your [Global rules](/global) apply everywhere, even outside a project.
3. **Verify.** Run `claude mcp list`, or type `/mcp` inside Claude Code.
4. **Test.** Start a new session in a project folder and ask which rules it is following. It should list your Global rules and name your project.

{{snippet:claude}}

Claude Code reads the session hook from `~/.claude/settings.json`. It prints your Global rules and the project's rules, focus and latest checkpoint once per session, so Claude starts with them without spending a tool call.

The Chat tab of the Claude desktop app uses the third snippet. Chats on claude.ai in a browser or on a phone cannot reach a program on your computer, so they do not see Project Moah.

Running your agent inside a container such as distrobox? The connection works as shown, because the `flatpak` command is forwarded to the host. To let Project Moah read your repository for Files and Git, see [[troubleshooting-container]].

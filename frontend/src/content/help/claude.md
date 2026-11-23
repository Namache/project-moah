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

**Why load your rules at the start?** The second snippet hands Claude your Global rules, the project's rules and its unfinished task, with what is already decided for it, before your first message, every session. Without it, Claude gets them only if it decides to ask, and it often does not. If your rules already load on their own, this step is set up.

The same file gets more hooks, so [Review](/review) and the chat stay in step. When Claude ends its turn on a question for you, one of them puts it into Review, so it waits there if you are away, and your reply in the chat settles it. When you answer in Review instead, the answer goes back to the chat that asked, and wakes it if it is idle. A chat you closed gets the answer the next time you write in it. They never stop Claude.

{{only flatpak}}
Running your agent inside a container such as distrobox? The connection works as shown, because the `flatpak` command is forwarded to the host. To let Project Moah read your repository for Files and Git, see [[troubleshooting-container]].

Project Moah keeps these hooks up to date itself. When it starts, it checks `~/.claude/settings.json`, the one Claude Code file it may change, and updates its own hooks there. Nothing to run after an update.
{{end}}
{{only deb}}
The `project-moah-mcp` command was installed with the app, so these commands work from any folder.
{{end}}
{{only windows}}
Run these commands in PowerShell. They contain the folder Project Moah is installed in on this computer, so if you reinstall it somewhere else, copy them again.
{{end}}

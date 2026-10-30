---
title: Connect Codex
category: Connect agents
summary: Set up OpenAI Codex to use Project Moah.
keywords: codex, openai, mcp, connect, setup, config
related: troubleshooting-container, claude, troubleshooting-mcp, troubleshooting-no-project
---

Project Moah gives agents a local MCP server. It runs on your computer and needs no network.

## Steps

1. **Install and open Project Moah** once, so its data exists.
2. **Connect Codex once.** The same connection serves every project: Project Moah finds the project from the folder Codex works in, and your [Global rules](/global) apply everywhere, even outside a project.
3. **Verify.** Run `codex mcp list`, or type `/mcp` inside Codex.
4. **Test.** Start a new session in a project folder and ask which rules it is following. It should list your Global rules and name your project.

{{snippet:codex}}

Codex has no start-up hook, so the line in `~/.codex/AGENTS.md` asks it to call `brain_brief` first. The server's own instructions say the same.

{{only flatpak}}
Running your agent inside a container such as distrobox? The connection works as shown, because the `flatpak` command is forwarded to the host. To let Project Moah read your repository for Files and Git, see [[troubleshooting-container]].
{{end}}
{{only deb}}
The `project-moah-mcp` command was installed with the app, so these commands work from any folder.
{{end}}
{{only windows}}
Run these commands in PowerShell. They contain the folder Project Moah is installed in on this computer, so if you reinstall it somewhere else, copy them again.
{{end}}

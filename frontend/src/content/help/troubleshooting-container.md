---
title: Using Project Moah with an agent in a container
category: Troubleshooting
summary: Why repository files and Git can be missing when your agent runs in distrobox or toolbox.
keywords: container, distrobox, toolbox, podman, bazzite, sandbox, flatpak, folder, share, filesystem, path
related: troubleshooting-repository, troubleshooting-git, claude, codex
---

## Problem

You run Claude Code or Codex inside a container such as distrobox, and Project Moah says the repository folder is not available, even though the agent can see it.

## Likely causes

- **Three views of one folder.** Your agent sees your files through the container, for example `/home/you/project`. The same folder lives on the host at `/var/home/you/project`. Project Moah runs in its own Flatpak sandbox, which can see neither unless you share the folder with it.
- **The connection itself is fine.** Inside a container, the `flatpak` command is forwarded to the host, so the agent starts Project Moah correctly. Tasks, memory, context, checkpoints and proposals all work. Only the repository folder is hidden.
- **Sandbox by design.** The app is not given your home folders, so it can only read what you choose to share.

## How to fix

1. **Easiest:** edit the project in Project Moah and use **Choose folder**. The system file chooser shares just that folder.
2. **Or share it with one command, read-only.** Run this once, in the container or on the host. Use the folder shown in Project Moah's message, which has the exact command for your project:

```bash
flatpak override --user --filesystem=~/projects/my-project:ro io.github.projectbrain.ProjectBrain
```

3. Reopen the project. The Files page should now show the branch and changes.
4. To undo: `flatpak override --user --nofilesystem=~/projects/my-project io.github.projectbrain.ProjectBrain`.

The folder is shared **read-only**, so Project Moah can read file names, Git status and commit messages and can never change your code. Other folders stay hidden.

If it still says the folder is not a Git repository, the folder is not one. Run `git status` there to check.

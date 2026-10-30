---
title: Projects
category: Core features
summary: Organize separate development projects.
keywords: project, workspace, switch, archive, repository, folder
related: tasks, files-and-git
---

A **project** keeps one product's tasks, memory, files and activity together. Projects never mix: an agent working on one never receives another project's decisions unless you search all projects yourself.

## Working with projects

- **Create** a project from *Projects*. You can add a repository folder now or later.
- **Switch** from the project list in the sidebar. The most recently opened projects come first.
- **Archive** a project you are not using. Archiving keeps all its data and never touches your source code. You can restore it at any time.

## Task IDs

Each project has a short prefix for its task IDs, such as CAMP in CAMP-037. It is chosen from the project name, and IDs are unique within a project.

## Sync from agents

You rarely need to create projects by hand. Project Moah reads the folder each Claude Code and Codex session started in and makes a project for each one, named after the folder. It checks every minute while the app is open, and again whenever an agent starts a session.

- Temporary folders, worktrees and Codex's one-off chat folders are skipped. Work in a subfolder counts toward its project.
- When a folder looks like an existing project that has no folder yet, Project Moah asks on the Projects page instead of guessing. Choose **Yes**, **No, make a new project**, or **Ignore this folder**.
- An ignored or archived project's folder is never brought back. Open **folders found** to undo an ignore.
- Only the folder path is read, never what was said in the session.

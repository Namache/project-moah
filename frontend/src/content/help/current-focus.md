---
title: Current focus
category: Core features
summary: Tell agents what you're actively working on.
keywords: focus, start work, current task, continue
related: tasks, context-packs
---

Each project can have one **current focus** task. When an agent asks for context without naming a task, Project Moah keeps to the task the agent's session already works on, and otherwise uses the focus. Without a focus, it uses the task the request names or plainly matches, and a bare "continue" gets the unfinished task the brief shows.

The brief every agent session starts with shows the focus task as unfinished work, with what is already decided for it. Without a focus, the brief shows the task of the latest checkpoint that has a task, while that task is in progress or blocked. A task parked in the backlog or waiting in review is not shown, and a checkpoint with no task, such as a small edit, does not hide the task before it. Failing that, it shows the only task in progress. With several tasks in progress and no checkpoint to go by, it shows none rather than guess. Set a focus to be sure which task agents pick up. The brief never changes the focus itself.

- **Start work** moves a task to In Progress and makes it the focus.
- **Clear focus** removes it without changing the task.
- Completing or archiving the focus task clears it automatically.

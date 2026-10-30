---
title: Context packs
category: Core features
summary: Understand how Project Moah saves context.
keywords: context, pack, tokens, budget, minimal, balanced, detailed, inspector, ai context
related: memory, handoffs, troubleshooting-context-too-large
---

Project Moah does not send your entire project history to an agent. Instead it builds a small **Context Pack** from what relates to the current task.

A pack may contain your Global rules, the current task, acceptance criteria, important decisions, the latest checkpoint, relevant files and known issues, plus memory that shelves and links lead to.

This reduces repeated explaining, helps agents resume work, and reduces project rediscovery. It does not promise a fixed saving, because that depends on your project and your agent.

## Detail levels

- **Minimal**: the task, unfinished requirements, next action, key decisions and the latest checkpoint.
- **Balanced**: adds rules, known issues, dependencies and recent activity.
- **Detailed**: adds more decisions, earlier checkpoints and replaced decisions.

## The size limit

The limit is an estimate that prevents runaway context. When it is tight, the least important items go first. Essential task details always stay, and no item is ever cut in half.

## AI context page

Open *AI context* in a project to preview exactly what an agent would receive, change the detail level, and include manual-only memory.

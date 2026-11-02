---
title: Context packs
category: Core features
summary: Understand how Project Moah saves context.
keywords: context, pack, tokens, budget, minimal, balanced, detailed, inspector, ai context
related: memory, handoffs, troubleshooting-context-too-large
---

Project Moah does not send your entire project history to an agent. Instead it builds a small **Context Pack** from what relates to the current task.

A pack may contain the current task, acceptance criteria, important decisions, the latest checkpoint, relevant files and known issues, plus memory that shelves and links lead to. Records that the task or its latest checkpoint name by ID come first. Every record the brief lists as already decided for the task is in its pack at any detail level; at Minimal, by title only. Memory hidden from AI never comes along.

This reduces repeated explaining, helps agents resume work, and reduces project rediscovery. It does not promise a fixed saving, because that depends on your project and your agent.

## Which task

A pack is for the task the agent names. Without one, it stays on the task the agent's session already works on, so a question asked in the middle of a task is about that task. Otherwise it uses the current focus. Without a focus, it uses the task the request names or plainly matches, and a bare "continue" gets the unfinished task the brief shows. The pack says which task it used. If nothing fits, it is an overview of the project.

## What agents get

An agent's pack leaves out what its session brief already gave it: your Global rules, and the rules and "left to do" of the project that brief showed. A pack for another project keeps that project's rules. It also leaves out recent activity and the shelves that woke up. They help you see why a pack holds what it does, but give an agent nothing to act on. A second request in the same session sends only what is new.

## Detail levels

- **Minimal**: the task, unfinished requirements, next action, key decisions and the latest checkpoint.
- **Balanced**: adds rules, known issues, dependencies and recent activity (activity only in the preview).
- **Detailed**: adds more decisions, earlier checkpoints and replaced decisions.

## The size limit

The limit is an estimate that prevents runaway context. When it is tight, the least important items go first. Essential task details always stay, and no item is ever cut in half.

## AI context page

Open *AI context* in a project to preview what an agent would receive, change the detail level, and include manual-only memory. The preview also shows your rules, recent activity and the shelves that woke up, which an agent's pack leaves out.

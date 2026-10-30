---
title: Memory
category: Core features
summary: Understand decisions, rules and project knowledge.
keywords: memory, decision, rule, fact, idea, bug, note, warning, lock, pin, supersede, visibility
related: context-packs, review, troubleshooting-outdated-context
---

Memory holds the knowledge that should survive between sessions.

## The types

- **Decision**: something you have chosen. Example: "Maximum party size is 4."
- **Rule**: a convention agents should consistently follow. Example: "Gameplay systems communicate through signals."
- **Fact**: established project information. Example: "The game uses Godot 4.x."
- **Idea**: something you are considering. **Ideas are not requirements.** Agents are told this every time one is shown.
- **Known issue** (bug): incorrect behavior you know about.
- **Note** and **Warning**: useful context, and cautions likely to affect work.

## Lock, pin, and AI visibility

**Locked** memory cannot be changed by an agent. If an agent wants a change, it makes a suggestion that waits in your *Inbox*.

**AI visibility** controls what agents may see:

- **Always**: available whenever relevant project context is built.
- **Relevant only**: included when related to the current task.
- **Manual only**: included only when you select it yourself.
- **Hidden**: never sent through Project Moah to coding agents.

## Replacing a decision

Do not overwrite an old decision. Replace it: the old one is kept as history, marked as replaced, and agents only see the new one.

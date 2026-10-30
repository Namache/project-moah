---
title: Brain health
category: Core features
summary: Check that agents can find what you saved, use it, and teach the brain what helps.
keywords: brain, health, links, orphans, feedback, shelves, suggestions, clusters, learning
related: context-packs, memory
---

Brain health sits under the brain on the **Brain** page. It answers three questions for each project.

## Findable

How much of the project's memory a link or a shelf leads to. Memory with no links is still there, but an agent only gets it when the words of its task happen to match. Above a quarter unlinked, Brain health asks you to look. **Review** opens the project's Guessed links, which lists that memory and any guessed links waiting for a yes or no.

Memory that goes into every pack anyway (always visible) and memory that only comes in when named (manual only) is not counted: a link would not change how it is found. Projects with fewer than ten memories are not judged.

For **Global rules**, rules reach every agent in every project. Other Global records (notes, facts, decisions) reach an agent only when a project links to them. Brain health warns about the ones nothing links to, because no agent ever sees them. Make such a record a rule, or set it to Always, if every agent should know it.

## Used lately

How many context packs agents asked for in the last 30 days. Agents save a checkpoint after real work, so when a project has many checkpoints and few packs, agents are working without your memory. The brief already tells them to call `brain_context_pack` first for every request; if they skip it, add that line to the project's own agent instructions (CLAUDE.md or AGENTS.md).

## Learning

How often agents said which records helped, after working from a pack. That feedback is the only way the brain learns: links that lead to useful records grow stronger, links nobody uses fade after a month. Below half, Brain health asks you to look.

## Details and suggestions

Open a project's row for the numbers behind the three signals, the topics the brain found (records that link to each other more than to the rest) and how closely each shelf's records link to each other. "Links brought in" says how much of what agents got came over links rather than a word search.

Suggestions offer to group records on shelves, add a keyword or a record to a shelf, merge two shelves, or share a lesson two projects both wrote. **Show the records** lists what a suggestion would touch. Shelves are views, so accepting never changes a record or a link. A recurring problem (several bugs and warnings around one topic) is a notice: **Write a rule** starts a new rule in that project. Dismissed suggestions are not offered again.

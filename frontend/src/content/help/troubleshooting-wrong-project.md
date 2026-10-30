---
title: Wrong project detected
category: Troubleshooting
summary: The agent received information from a different project than expected.
keywords: wrong project, ambiguous, detection, candidates
related: troubleshooting-mcp, review
---

## Problem

The agent received information from a different project than expected.

## Likely causes

- Two projects share the same repository folder, so Project Moah refused to guess.
- The agent was started in a folder that belongs to another project.

## How to fix

1. Give each project its own repository folder.
2. Start the agent in the right project's folder, or name the project in your request, for example "in Trailhead". Every Project Moah tool accepts a project name.
3. Wrong-project context is treated as worse than none, so an ambiguous match returns the candidates and asks the agent to choose.

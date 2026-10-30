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
- The server was set up with another project's name.

## How to fix

1. Give each project its own repository folder.
2. Set the project explicitly: add `--project your-project` to the server command.
3. Wrong-project context is treated as worse than none, so an ambiguous match returns the candidates and asks the agent to choose.

---
title: Context contains outdated information
category: Troubleshooting
summary: The agent was told something that is no longer true.
keywords: outdated, stale, old, superseded, replaced
related: troubleshooting-mcp, review
---

## Problem

The agent was told something that is no longer true.

## Likely causes

- An old decision was edited instead of replaced, or never replaced.
- A file note describes a file that has since changed.
- A memory is marked always visible but is out of date.

## How to fix

1. Replace the decision under *Memory*, so the old one becomes history.
2. Mark wrong memory as *wrong* or archive it.
3. On *Files*, review notes marked *Changed since review*.
4. Check *AI Context* to preview what is sent.

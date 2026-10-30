---
title: Git information missing
category: Troubleshooting
summary: Branch, changes or commits are not shown.
keywords: git, branch, commits, status, missing
related: troubleshooting-mcp, review
---

## Problem

Branch, changes or commits are not shown.

## Likely causes

- Git is not available to Project Moah.
- The folder is not a Git repository, or has no commits yet.
- Git refused the repository because of folder ownership.

## How to fix

1. Open *Files* and read the message at the top, which names the cause.
2. Make sure the folder is a Git repository with at least one commit.
3. Fix folder ownership, or ask Git to trust the folder.

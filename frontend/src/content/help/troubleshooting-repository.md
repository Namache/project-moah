---
title: Repository unavailable
category: Troubleshooting
summary: The Files page says the repository folder could not be found or read.
keywords: repository, folder, path, missing, moved, permission
related: troubleshooting-container, troubleshooting-mcp, review
---

## Problem

The Files page says the repository folder could not be found or read.

## Likely causes

- The folder was moved or renamed.
- The app has not been given access to that folder.
- The drive is not mounted.
- Your agent runs in a container, and the folder was never shared with Project Moah's sandbox. See [[troubleshooting-container]].

## How to fix

1. Edit the project and choose the folder again with *Choose folder*.
2. Remount the drive and reopen the project.
3. Tasks and memory keep working without the repository.

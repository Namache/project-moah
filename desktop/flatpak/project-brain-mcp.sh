#!/bin/sh
# Starts Project Moah's local MCP server for a coding agent, over standard input and output.
# It uses the same data as the app and needs no network. Example:
#   flatpak run --command=project-moah-mcp io.github.projectbrain.ProjectBrain --agent claude --project trailhead
exec /app/lib/project-brain/resources/bin/project-brain-backend --mcp "$@"

# MCP integration

Project Moah exposes a local MCP server so coding agents can read project state and record their work. It runs over standard input and output, needs no network, and shares the app's database.

## Documentation checked before building (2026-10-10)

| Topic | Source | What was relied on |
| --- | --- | --- |
| Claude Code | https://code.claude.com/docs/en/mcp | `claude mcp add --transport stdio [--scope project] <name> -- <command> [args]`; `.mcp.json` with `mcpServers.<name>` `{type, command, args}`; `claude mcp list` and `/mcp` to verify. |
| Codex | https://developers.openai.com/codex/mcp | `codex mcp add <name> -- <command> [args]`; `[mcp_servers.<name>]` with `command`, `args`, `startup_timeout_sec` in `~/.codex/config.toml` or a trusted project's `.codex/config.toml`; `codex mcp list` and `/mcp` to verify. |
| Python SDK | https://pypi.org/project/mcp/ and the installed package | `mcp` 2.3.0 (Python 3.10+). v2 uses `from mcp.server import MCPServer`, `@server.tool(annotations=ToolAnnotations(...))`, `server.run("stdio")`, and `ToolError` for messages the agent should see. The older `FastMCP` name is not used. |

Vendor syntax is isolated in `frontend/src/content/integrations.ts` (the commands shown in Help and Settings). The server itself is in `backend/app/mcp/`. A vendor change should only touch the first.

## Starting the server

Installed app (Flatpak), what an agent runs:

```bash
flatpak run --command=project-moah-mcp io.github.projectbrain.ProjectBrain --agent claude --project trailhead
```

From source: `python -m app.mcp --agent codex --project trailhead` inside `backend/`. `--agent` names who is connecting (`claude`, `codex`, or anything else, recorded as system). `--project` sets a default project; without it the agent must pass one, or the working folder must match exactly one project's repository folder.

## One connection per agent (2026-10-11)

Each agent is connected once, for every project, without `--project`. The Connect button in Help and `project-brain-backend --connect` (`backend/app/services/agent_connect.py`, also reached through `project-moah-mcp --connect`) write all of this in one step; they keep other settings, save a `.moah-backup` of each file they first change, and can be run again. An agent following [INSTALL.md](../INSTALL.md) uses them.

- Claude Code: user scope (`claude mcp add --scope user project-moah -- flatpak run --command=project-moah-mcp io.github.projectbrain.ProjectBrain --agent claude`), plus a `SessionStart` hook in `~/.claude/settings.json` that runs `project-brain-mcp --brief --cwd "$CLAUDE_PROJECT_DIR"`. Hook output becomes session context, so the brief costs no tool call.
- Codex: `[mcp_servers.project-moah]` in `~/.codex/config.toml`, and a line in `~/.codex/AGENTS.md` asking it to call `brain_brief` first.
- Claude desktop app, Chat tab: `mcpServers.project-moah` in `~/.config/Claude/claude_desktop_config.json`.

The project comes from the agent's working folder, compared as path text (`/var/home` and `/home` are one spelling), so a folder the sandbox cannot open still matches. Outside every project the brief carries only the Global rules. Each brief also runs **Sync from agents**: the folders Claude Code and Codex sessions start in become projects (temporary folders, worktrees and Codex one-off chats skipped); a folder whose name resembles an existing folderless project is asked about on the Projects page, never guessed.

## Tools

Second opinion: `brain_second_opinion` (off until switched on in Settings, Agents; returns a read-only command for the asking agent to run in its own terminal, so the person approves it there; Project Moah never starts an agent itself). Read-only: `brain_brief` (global rules, project rules, focus, latest checkpoint and how to keep Project Moah current; it also runs Sync from agents), `brain_list_projects`, `brain_project_state`, `brain_context_pack` (`operation` is detected from the task when omitted; `explain=true` adds why each record came in and what was left out; Global rules are left out because the brief gave them, `global_rules=true` puts them back; a minimal pack still keeps the warnings and open bugs that match the work; the pack ends with a retrieval id), `brain_get_task`, `brain_view_images` (the pictures a person attached to a task or memory record, returned as MCP image content; records with images list them under `images`, and context packs note them as `[1 image attached: brain_view_images PROJ-6]`; memory hidden from agents is refused), `brain_list_tasks`, `brain_search`, `brain_get_related`, `brain_changed_files`, `brain_links` (what a record connects to, each link read from that record), `brain_shelves` (shelves, their members, and how strongly a task wakes each), `brain_link_review` (candidate links nobody has confirmed, orphan memory nothing links to, the graph's health, and shelves the brain suggests growing or merging).

Writes: `brain_create_task`, `brain_update_task`, `brain_create_checkpoint`, `brain_create_memory` (with `related`, `tasks` and `shelf`; without one, the record is filed on the deepest shelf its words name, and so is a new task), `brain_link_memories`, `brain_update_memory`, `brain_supersede_memory`, `brain_create_proposal`, `brain_link` (a typed link between two records; agents cannot remove a link a person made), `brain_update_shelf` (file records on a shelf, or create, change or delete one; a shelf is a name or a path such as "Knowledge > Software engineering > Frontend", and `shared` puts a new one on the shared tree every project files on, where each project sees only its own records), `brain_retrieval_feedback` (after working from a pack, name the records that helped and the ones that were noise; links learn per kind of work, a useful record the pack missed gets linked to the task, and a guessed link between two records that both helped is confirmed).

### How writes join the Brain

Every write links the record as it is saved, so nothing an agent records stays an orphan:

- **What the agent names.** `brain_create_memory` takes `related` (any record: memory, a task, `file:src/a.gd`, `global:RULE-3`) and `tasks`. The memory, task and update tools take `links`, each written `"relationship target"`, for example `["caused_by DEC-002", "depends on CAMP-3"]`. A name that matches nothing is reported in `not_linked` and the record is still saved; it used to fail the whole write.
- **What the text names.** DEC-004, a file with notes, or `global RULE-3` in a title, content, description or next action becomes an active `references` link. This runs on edits, replacements and checkpoints too, not only on creation. Records with similar titles become candidate links, which are never followed until confirmed.
- **The session's task.** Each MCP server process serves one agent session and remembers the task it works on: the task of its last context pack (the focus task when none is named, but not for a search-only pack), a task set to `in_progress`, or the task of its last checkpoint. A record written without naming a task is linked to it (`relates_to`, active, confidence 0.6, "written while working on CAMP-3 in the same session"); a task created meanwhile is linked to it too; a checkpoint without a task reports on it, and the records the checkpoint names are linked to that task. `brain_brief` starts a new session and forgets the task, and so does a pause of two hours between tool calls. `brain_project_state` shows the session's task and each pack ends by naming it. Limitation: Claude Code keeps the server running across `/clear`, so a record written after `/clear` but before the next context pack can still be linked to the previous task, within those two hours; reject such a link in the Brain or with `brain_link(remove=true)`. The task lives in the server's memory, so a server the client restarts mid-session forgets it, and records are linked to no task until the next context pack. A client that runs one server for several chats gives them one shared session task.
- **Replacing memory keeps its links**: tags, tasks, memory links, file notes and typed links all move to the new record.

The app asks the backend for a change counter (`GET /api/brain/version`) every four seconds while its window is visible, and refreshes what is on screen when the counter moves (the Brain, tasks, memory, reviews), so records and links an agent makes appear while you watch.

Each tool states whether it only reads. Errors are plain sentences that say what to do next.

## Agents inside a container (distrobox, toolbox)

Checked with an agent inside a distrobox container on an immutable Fedora-based desktop: the container's `flatpak` is a forwarder to the host, and the MCP connection works through it, including standard input and output. What the agent can see and what Project Moah can see differ, though:

| View | Path to the same folder |
| --- | --- |
| Inside the container | `/home/you/project` |
| On the host | `/var/home/you/project` (`/home` is a link to it) |
| Inside Project Moah's Flatpak | nothing, until shared |

The sandbox has the same `/home` link, so once a folder is shared, both spellings resolve and no path translation is needed. Share it with the Choose folder button, or read-only with `flatpak override --user --filesystem=<folder>:ro io.github.projectbrain.ProjectBrain` (undo with `--nofilesystem=<folder>`). Verified with a temporary grant: only that folder appeared, and writing to it failed. Until a folder is shared, the Git status is `not_shared`, with a message that says how to fix it, and everything else works. Pass `--project` in the setup command, as the guides do, because the container's working folder is not visible to the app and cannot be matched.

## Rules the server enforces

- **No guessing the project.** An explicit project wins. Otherwise the working folder must lie inside exactly one project's repository folder, the deepest match. Two projects with the same folder, or no match, return the candidates and ask the agent to choose.
- **Locked memory cannot be changed by an agent.** Edits, replacement, archiving, invalidating and deleting are refused with a message pointing to `brain_create_proposal`. Agents cannot lock or unlock.
- **Completing or archiving a task becomes a proposal.** `brain_update_task` applies other fields and creates a proposal for those two.
- **Agent writes are attributed.** Every activity event and agent-created record names the agent. Agent-created memory is unlocked and marked as agent-written.
- **Archived projects are read-only** for agents.
- **Search across projects** needs `scope="all"`, and its results are labelled by project.
- Context packs follow the safety rules in `ARCHITECTURE.md`: hidden, archived, replaced and unrelated records are never included, and manual-only memory only when named.

## Verification status

| Item | Status |
| --- | --- |
| Server implemented, 25 tools, schemas without internal parameters | Tested: backend tests drive the real server as a subprocess over stdio with the SDK's own client. |
| Project detection, locks, attribution, proposals, archived projects | Tested the same way. |
| Packaged launcher (`project-moah-mcp` in the Flatpak; `project-brain-mcp` still works) | See the implementation plan for the packaged check. |
| Connection from the real Claude Code application | Verified by hand 2026-10-11: Claude Code loaded all tools from the installed Flatpak and `brain_project_state` answered. The user-scope registration was written by Claude Code's own `claude mcp add`. |
| Session brief hook | Verified 2026-10-11 by running the hook command exactly as configured: the installed app printed the brief for this repository and for a subfolder in about 1.2 to 1.5 s. Not yet seen arriving in a fresh Claude Code session. |
| Codex and the Claude desktop Chat tab | Configured 2026-10-11 (the TOML parses, the JSON keeps all other settings). **Not yet verified by hand**; both need a restart to load the server. |

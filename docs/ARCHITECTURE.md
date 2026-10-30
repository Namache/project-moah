# Architecture

Project Moah is a local desktop application for several independent software projects. A Python API owns persistence and domain rules; a React application presents the workspace inside an Electron window. The packaged app starts its bundled Python backend automatically. SQLite stores data in the user's app data directory rather than in managed repositories. Browser access remains available for source development only.

## Phase 1 boundaries

```text
Electron window (bundled React, TypeScript, Vite assets)
             |
        /api requests on loopback
             |
Bundled FastAPI process -> project operations -> SQLAlchemy -> SQLite
                                              |
                                           migrations
```

Electron owns the backend process lifecycle: it starts the platform-specific bundled executable, waits until the API is ready before displaying the workspace, and stops the child on exit. The frontend build is included in the package, so using the app requires neither a development server nor a system browser. The API binds only to loopback. The desktop distribution is a Windows executable or a Flatpak with its own application launcher. Source development can still run Vite and FastAPI separately.

The Flatpak sandbox grants loopback networking to connect the window and backend. Its XDG data directory is private and persistent. A stored project path is only metadata during Phase 1; future repository access must use an appropriate file portal or deliberate filesystem permission.

Phase 1 contains project creation, listing, editing, archiving, and switching. A project may have no repository path. A provided `root_path` must be absolute, but it need not exist yet. It is metadata in this phase; no repository scan or Git command runs because a path was saved. The development seed creates several clearly distinct projects.

The REST contract starts with `GET/POST /api/projects` and `GET/PATCH /api/projects/{id}`. An archived project has `status: archived`; the API also offers `POST /api/projects/{id}/archive`. Archiving updates a project's status instead of deleting its source directory. The UI keeps server records in TanStack Query and puts the selected project ID in the URL; the API remains the authority for persisted data.

## Invariants to preserve as the app grows

- Every future project-owned record carries a `project_id`. A nested API route must verify that the record belongs to the route's project before reading or changing it.
- A normal project search or context request cannot include another project's data. Explicit global search will be a separate human action and will identify each result's project.
- Structured records, not conversation history, hold durable project truth. Human review controls agent proposals and locked memory changes.
- Services hold domain rules; transport adapters for HTTP and, later, MCP call those services. MCP client configuration must not shape the data model.
- Keep the API on loopback and data local by default. The desktop backend must terminate with its owning window. Never run shell commands from saved record text, and validate paths before future file or Git access.

## Search, context, and agents (Phases 5 to 10)

**Search.** One FTS5 table indexes projects, tasks, memory, checkpoints and file notes. Database triggers keep it current, so every writer is covered. A project search always filters on one project; the all-projects search is a separate route that a person must choose, and its results name their project. Queries are split into quoted words, so punctuation can never break them. Results are for reading and never become agent context on their own.

**Context packs.** `ContextService` builds a compact summary for one task. It reads through a single project, drops hidden, archived, replaced and unrelated records first, ranks what remains, and fits it to an approximate size. Ranking signals: linked to the task (strongest), always-visible, pinned, locked, importance, and a search match against the task and query. Items sit in priority tiers; essential task information is always kept, other tiers are kept in order while they fit, and an item is never cut in half. Manual-only memory needs an explicit name. Ideas appear only when related, labelled as not requirements. Minimal, balanced and detailed select different amounts. The same selection feeds the handoff note.

**Repository awareness.** Git runs only as fixed read-only commands with a timeout, against the project's own folder, never through a shell. Every failure (no folder, folder moved, no Git, not a repository, ownership refusal) becomes a plain status and the rest of the app keeps working. File notes store metadata only. The Flatpak bundles Git, and repository folders reach the app through the system folder chooser, which grants access to the folder the person picks.

**Agents.** The MCP server (`backend/app/mcp`) is a second front end to the same services. It never reimplements a rule. It sets the acting agent for each call, so activity and provenance name the agent, and locked memory and task completion stay in human hands through proposals. See `MCP.md`.

**Proposals.** An agent's suggestion is stored, validated, and shown with a diff. Accepting applies it as a person through the normal services. A person may edit it first. A failed accept changes nothing.

## Boundaries still outside V1

Cloud sync, accounts, team features and embeddings are out of scope. The data model leaves room for embeddings as an optional retrieval layer later.

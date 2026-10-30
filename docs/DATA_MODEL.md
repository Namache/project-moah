# Data model

## Implemented in Phase 1

One implicit local workspace contains many `Project` rows. A project exists independently of a source repository.

| Field | Meaning |
| --- | --- |
| `id` | Stable internal identifier. API clients use it to select a project. |
| `name` | Human readable project name. |
| `name_key` | Internal normalized name for case-insensitive uniqueness. |
| `slug` | Short, unique workspace identifier, with a suffix when generated slugs collide. |
| `description` | Optional summary. |
| `icon`, `accent` | Optional display cues. |
| `root_path` | Optional absolute path to a repository; saved only as metadata in Phase 1. The path need not exist yet. |
| `status` | `active`, `paused`, `completed`, or `archived`. |
| `current_focus_task_id` | Nullable placeholder; Phase 2 must validate a task in the same project before setting it. |
| `created_at`, `updated_at` | Creation and last edit timestamps. |
| `last_opened_at`, `archived_at` | Optional lifecycle timestamps. |

The Phase 1 migration is the source of truth for physical columns. A current focus task can only be set after tasks exist; no placeholder task row is implied by the seed data. Project names and slugs are unique across the implicit workspace. An archived project is normally omitted from the list API but remains readable and restorable.

The database belongs to Project Moah, not to any managed repository. Migrations change its schema. Seed data must be opt-in and repeatable. Archive preserves the project row and must never remove repository files. Deleting a Project Moah record must never delete its source repository.

## Implemented in Phase 2 (backend)

| Table | Purpose and rules |
| --- | --- |
| `milestones` | Project-scoped; `planned`, `active`, `completed`, `archived`; ordered by `sort_order`. Progress counts exclude archived tasks. |
| `tasks` | Project-scoped; optional milestone. `human_id` is `PREFIX-NNN`, unique per project, numbered per prefix. The prefix comes from the request, else `projects.task_prefix`, else the first four letters of the project name. `sort_order` orders a board column. |
| `task_acceptance_criteria` | Ordered, checkable criteria per task; deleted with the task. |
| `task_relationships` | Stored types `parent`, `depends_on`, `related_to`, `supersedes`. The API also accepts `child`, `blocks` and `superseded_by`, stored as the inverse. One parent per task; parent, dependency and supersession loops are rejected. |
| `tags`, `task_tags` | Lightweight per-project tags, matched case-insensitively. |

`projects` gained `task_prefix` and a foreign key from `current_focus_task_id` to the task.

**Same-project integrity is enforced by SQLite.** Children reference parents through composite `(id, project_id)` foreign keys. A task cannot point at another project's milestone or tag, relate to another project's task, or be another project's focus, even through raw SQL. Services also report other projects' records as "not found".

**Status side effects:** entering `in_progress` stamps `started_at` once. `completed` and `archived` stamp their times and clear them when the task leaves that status. A completed or archived task stops being the current focus. "Start work" moves a task to In Progress and makes it the focus. Tasks are normally archived; permanent delete exists for mistakes.

## Implemented in Phase 3

| Table | Purpose and rules |
| --- | --- |
| `memories` | Project-scoped records of type `decision`, `rule`, `fact`, `idea`, `bug`, `note`, or `warning`. Human IDs are `DEC-001`, `RULE-001`, `FACT-001`, `IDEA-001`, `BUG-001`, `NOTE-001`, `WARN-001`, numbered per type. The type never changes. Status is `active`, `superseded`, `invalidated`, or `archived`. Importance is `low` to `critical`. AI visibility is `always`, `relevant_only`, `manual_only`, or `hidden`. Optional source and confidence fields record where a memory came from. |
| `memory_tags`, `memory_tasks` | Tags reuse the project's tags. Task links connect a memory to the tasks it informs. |

**Supersession:** replacing a memory creates a new one of the same type, marks the old one `superseded`, and links them with `supersedes_id`. A memory can be replaced only once, so history forms a chain. The new one inherits tags, task links, pin and lock unless overridden. Earlier records keep their text, and no record in a replacement chain can be permanently deleted. `GET .../memory/{id}/history` returns the whole chain and its current record. Lists show only `active` records unless asked.

**Locking is enforced in the service, not the UI.** Any actor other than a person gets HTTP 423 when it tries to edit the title, content, importance, AI visibility, confidence, source, or tags, or replace, invalidate, archive, or delete a locked memory. Only a person can lock, unlock, or permanently delete a memory, and a locked one must be unlocked before it is deleted. Pinning and task links stay allowed. Agent-created memory is recorded with `source_type` `agent` and the agent's name. The REST API serves the app itself, so it always acts as a person. The Phase 8 MCP adapter must pass its agent name as the actor.

**Isolation:** composite foreign keys stop a memory from replacing, tagging, or linking across projects. Search in this phase is a literal text match on title, content, and ID. FTS5 arrives in Phase 5.

## Implemented in Phase 4

| Table | Purpose and rules |
| --- | --- |
| `checkpoints` | Project-scoped progress snapshots. An optional task link is constrained to the same project. Each checkpoint stores a title, summary, completed work, remaining work, problems, next steps, optional author/agent and Git commit, and creation/update times. Checkpoints remain in history when a newer one is added. |
| `activity_events` | Append-only audit entries with project ID, optional same-project task ID, event type, actor type and optional name, timestamp, entity type and ID, and JSON metadata. Activity is for review, not event sourcing or state restoration. |

**Latest resolution:** `GET /api/projects/{project_id}/checkpoints/latest` returns the newest checkpoint by creation time and ID. An optional `task` query narrows it to one task; a missing checkpoint returns 404, which the UI treats as an empty state. Checkpoints can be listed, created, read, and edited through `/api/projects/{project_id}/checkpoints`. The API does not delete checkpoint history.

**Activity reads:** `GET /api/projects/{project_id}/activity` and `GET /api/activity` return newest-first pages. Repeated `event_type`, `actor_type`, and `entity_type` filters and `limit`/`offset` are supported; the project route also accepts `task`, and workspace reads may filter by `project_id`. Project name is joined into each read for the workspace timeline. The UI presents known metadata fields as readable details rather than raw JSON. Git commit events await Phase 7 repository awareness.

**Attribution and transaction rule:** Actor types are `human`, `codex`, `claude`, and `system`. The REST routes serve the human desktop app; service calls can specify an agent actor for later integrations. Project, milestone, task, memory, and checkpoint writes stage an activity event in the same database transaction as the domain change. The timeline is not a substitute for the canonical project, task, memory, or checkpoint tables.

**Same-project integrity:** Composite foreign keys and checks keep checkpoint and activity task links inside the owning project. Services also resolve task references within the route's project. Generic `entity_type`/`entity_id` values identify what changed for the audit UI; they are not cross-project join keys.

## Implemented in Phase 5 (backend)

`search_index` is an FTS5 virtual table with one row per project, task, memory, or checkpoint. Searchable text: project name and description; task title, ID, description, next action, criteria, and tags; memory title, ID, content, and tags; checkpoint title and all its text sections. Filter columns (entity type, entity ID, project ID, memory type, status, updated time) are stored unindexed beside each row. It is derived data: triggers rebuild a record's row whenever the record changes, and the migration can recreate it from the source tables, so a backup needs nothing special. Activity events are not indexed.

## Implemented in Phases 6 to 10 (backend)

**Files and Git (migration `0006_files_git`).** `project_files` holds notes about a repository path (purpose, summary, language, content hash), with `file_symbols` and links to tasks, memory and checkpoints, all through same-project composite foreign keys. Paths are relative, POSIX, and validated: no absolute paths, `..`, backslashes or drive letters. Source text is never stored. `git_commits` keeps metadata for commits a person linked to tasks, with `commit_tasks` (`confirmed` or `suggested`) and `commit_files`, so history survives a moved repository. Task IDs found in commit messages are shown as suggestions and only stored when confirmed. Files are included in search by triggers on these tables.

**AI proposals (migration `0007_proposals`).** `ai_proposals` stores an agent's suggestion: type, target record, a validated payload, a snapshot of the target for a readable diff, the reason, and status `pending`, `accepted`, or `rejected`, with the reviewer's note and any edited payload. Accepting applies the change as a person through the normal services, so every rule and activity event applies. A failed accept changes nothing and records why.

**No new tables for context packs and handoffs.** They are computed from existing records at request time (see `ARCHITECTURE.md`).

**Backups.** The whole database is one SQLite file. `GET /api/system/export` makes a consistent copy with SQLite's backup API. The search index is derived data that migrations can rebuild.

## Planned relational model

These are design targets for later phases, not claims about Phase 1 tables.

| Phase | Entities and key relationships |
| --- | --- |
| 5–6 | Project-scoped FTS5 indexes and context selection over canonical records. Global search is explicit and separate from agent context. |
| 7 | `File(project_id)`, optional symbols, commit metadata, and typed join tables connecting files to tasks, memory, checkpoints, and commits. Store metadata, not full source copies. |

Use SQLite foreign keys, indexes, uniqueness constraints, and transactions. Foreign keys alone do not prove two referenced records belong to the same project; services must validate that relationship before a write, with composite constraints where useful. Keep historical memory records when superseded and exclude stale or hidden records from ordinary agent retrieval.

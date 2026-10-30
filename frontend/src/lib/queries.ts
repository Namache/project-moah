import type { QueryClient } from "@tanstack/react-query";

/**
 * Cache keys shared by more than one module. Project-scoped keys always put the project ID
 * second, which is what lets invalidateProject find every one of them.
 */
export const queryKeys = {
  projects: ["projects"] as const,
  project: (projectId: string) => ["project", projectId] as const,
  overviews: ["overviews"] as const,
  workspaceTasks: ["workspace-tasks"] as const,
  tasks: (projectId: string) => ["tasks", projectId] as const,
  archivedTasks: (projectId: string) => ["tasks", projectId, "archived"] as const,
  task: (projectId: string, taskRef: string) => ["task", projectId, taskRef] as const,
  milestones: (projectId: string) => ["milestones", projectId] as const,
  memory: (projectId: string) => ["memory", projectId] as const,
  checkpoints: (projectId: string) => ["checkpoints", projectId] as const,
  proposals: (projectId: string) => ["proposals", projectId] as const,
  proposalsPending: ["proposals-pending"] as const,
  agentSettings: ["agent-settings"] as const,
  taskSettings: ["task-settings"] as const,
  agentFolders: ["agent-folders"] as const,
};

/** Views that combine every project: lists, overviews, search, activity, and the review badge. */
const WORKSPACE_KEYS = ["projects", "overviews", "workspace-tasks", "search", "activity", "proposals-pending", "brain-all", "brain-health"];

/** Refreshes everything the workspace-wide views show. */
export function invalidateWorkspace(client: QueryClient): Promise<unknown> {
  return Promise.all(WORKSPACE_KEYS.map((key) => client.invalidateQueries({ queryKey: [key] })));
}

// Views that do not show knowledge: usage reads agent logs, sync scans folders, Git calls run
// commands. Everything else is built from records an agent can change.
const NOT_KNOWLEDGE = new Set(["brain-version", "usage", "usage-slice", "agent-folders", "agent-settings", "diagnostics", "file-tree", "commits", "file-history"]);

/** Refreshes every view built from knowledge, after something outside this window changed it. */
export function invalidateKnowledge(client: QueryClient): Promise<unknown> {
  return client.invalidateQueries({ predicate: (query) => !NOT_KNOWLEDGE.has(String(query.queryKey[0])) });
}

/**
 * Refreshes every view of one project and the workspace-wide views built from it.
 * Changes ripple: a task edit changes context packs and search, a memory edit changes file links, and so on,
 * so one helper refreshes them all rather than each mutation guessing. Only views on screen refetch at once.
 */
export function invalidateProject(client: QueryClient, projectId: string): Promise<unknown> {
  return Promise.all([
    client.invalidateQueries({ predicate: (query) => query.queryKey[1] === projectId }),
    invalidateWorkspace(client),
  ]);
}

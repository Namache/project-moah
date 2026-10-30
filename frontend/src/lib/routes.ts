import { labels, msg } from "./i18n";
/** The reserved scope for rules and memory shared by every project (backend GLOBAL_PROJECT_ID). */
export const GLOBAL_ID = "global";

export type ProjectSection = "" | "tasks" | "memory" | "context" | "review" | "files" | "activity";

/** A project's sections in the order its tabs (and the command palette) show them. */
export const projectSections: { label: string; path: ProjectSection }[] = [labels({ label: msg("Overview"), path: "" }, ["label"]), labels({ label: msg("Tasks"), path: "tasks" }, ["label"]), labels({ label: msg("Memory"), path: "memory" }, ["label"]), labels({ label: msg("AI context"), path: "context" }, ["label"]), labels({ label: msg("Inbox"), path: "review" }, ["label"]), labels({ label: msg("Files"), path: "files" }, ["label"]), labels({ label: msg("Activity"), path: "activity" }, ["label"])];
type Query = Record<string, string | null | undefined>;

function withQuery(path: string, query: Query = {}): string {
  const pairs = Object.entries(query).filter((entry): entry is [string, string] => Boolean(entry[1]));
  return pairs.length ? `${path}?${pairs.map(([key, value]) => `${key}=${encodeURIComponent(value)}`).join("&")}` : path;
}

/**
 * Where a project's pages live. The Global scope has its own pages: its rules and memory at /global
 * and its review at /global/review, so links into it never land on a project page.
 */
export function projectPath(projectId: string, section: ProjectSection = "", query?: Query): string {
  if (projectId === GLOBAL_ID) return withQuery(section === "review" ? "/global/review" : "/global", query);
  return withQuery(`/projects/${encodeURIComponent(projectId)}${section ? `/${section}` : ""}`, query);
}

export const taskPath = (projectId: string, taskRef: string) => projectPath(projectId, "tasks", { task: taskRef });
export const memoryPath = (projectId: string, memoryRef: string) => projectPath(projectId, "memory", { memory: memoryRef });
export const checkpointPath = (projectId: string, checkpointId: string) => projectPath(projectId, "", { checkpoint: checkpointId });

import { request } from "./client";
import type { ContextOptions, ContextPack } from "../types/context";

function contextPath(projectId: string, options: ContextOptions): string {
  const params = new URLSearchParams({ detail: options.detail });
  if (options.task) params.set("task", options.task);
  if (options.query?.trim()) params.set("q", options.query.trim());
  if (options.budget) params.set("budget", String(options.budget));
  options.include?.forEach((ref) => params.append("include", ref));
  options.exclude?.forEach((ref) => params.append("exclude", ref));
  return `/projects/${encodeURIComponent(projectId)}/context?${params}`;
}

export const contextApi = {
  pack: (projectId: string, options: ContextOptions, signal?: AbortSignal) => request<ContextPack>(contextPath(projectId, options), { signal }),
};

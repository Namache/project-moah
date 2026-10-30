import { request } from "./client";
import type { ActivityEvent, ActivityFilters } from "../types/activity";

function path(base: string, filters: ActivityFilters): string {
  const params = new URLSearchParams();
  filters.eventTypes?.forEach((value) => params.append("event_type", value));
  filters.actorTypes?.forEach((value) => params.append("actor_type", value));
  filters.entityTypes?.forEach((value) => params.append("entity_type", value));
  if (filters.task) params.set("task", filters.task);
  if (filters.projectId) params.set("project_id", filters.projectId);
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  if (filters.offset !== undefined) params.set("offset", String(filters.offset));
  const query = params.toString();
  return `${base}${query ? `?${query}` : ""}`;
}

export const activityApi = {
  project: (projectId: string, filters: ActivityFilters = {}, signal?: AbortSignal) => request<ActivityEvent[]>(path(`/projects/${encodeURIComponent(projectId)}/activity`, filters), { signal }),
  workspace: (filters: ActivityFilters = {}, signal?: AbortSignal) => request<ActivityEvent[]>(path("/activity", filters), { signal }),
};

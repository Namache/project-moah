import { request } from "./client";
import type { SearchFilters, SearchResponse } from "../types/search";

function searchPath(projectId: string | null, filters: SearchFilters): string {
  const params = new URLSearchParams();
  params.set("q", filters.q.trim());
  filters.entityTypes?.forEach((value) => params.append("entity_type", value));
  filters.memoryTypes?.forEach((value) => params.append("memory_type", value));
  filters.memoryStatuses?.forEach((value) => params.append("memory_status", value));
  if (filters.includeArchived) params.set("include_archived", "true");
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  if (filters.offset !== undefined) params.set("offset", String(filters.offset));
  const base = projectId === null ? "/search" : `/projects/${encodeURIComponent(projectId)}/search`;
  return `${base}?${params}`;
}

export const searchApi = {
  project: (projectId: string, filters: SearchFilters, signal?: AbortSignal) => request<SearchResponse>(searchPath(projectId, filters), { signal }),
  workspace: (filters: SearchFilters, signal?: AbortSignal) => request<SearchResponse>(searchPath(null, filters), { signal }),
};

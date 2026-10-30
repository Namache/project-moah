import { json, request } from "./client";
import type { MemoryChanges, MemoryCounts, MemoryFilters, MemoryHistory, MemoryInput, MemoryRecord, MemoryReplacement } from "../types/memory";

const base = (projectId: string) => `/projects/${encodeURIComponent(projectId)}/memory`;
const one = (projectId: string, ref: string) => `${base(projectId)}/${encodeURIComponent(ref)}`;

function listPath(projectId: string, filters: MemoryFilters): string {
  const params = new URLSearchParams();
  filters.types?.forEach((value) => params.append("type", value));
  filters.statuses?.forEach((value) => params.append("status", value));
  filters.visibility?.forEach((value) => params.append("visibility", value));
  if (filters.pinned !== undefined) params.set("pinned", String(filters.pinned));
  if (filters.locked !== undefined) params.set("locked", String(filters.locked));
  if (filters.resolved !== undefined) params.set("resolved", String(filters.resolved));
  if (filters.tag) params.set("tag", filters.tag);
  if (filters.task) params.set("task", filters.task);
  if (filters.q) params.set("q", filters.q);
  if (filters.sort) params.set("sort", filters.sort);
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  if (filters.offset !== undefined) params.set("offset", String(filters.offset));
  const query = params.toString();
  return `${base(projectId)}${query ? `?${query}` : ""}`;
}

export const memoryApi = {
  list: (projectId: string, filters: MemoryFilters = {}, signal?: AbortSignal) => request<MemoryRecord[]>(listPath(projectId, filters), { signal }),
  counts: (projectId: string, signal?: AbortSignal) => request<MemoryCounts>(`${base(projectId)}/counts`, { signal }),
  get: (projectId: string, ref: string, signal?: AbortSignal) => request<MemoryRecord>(one(projectId, ref), { signal }),
  history: (projectId: string, ref: string, signal?: AbortSignal) => request<MemoryHistory>(`${one(projectId, ref)}/history`, { signal }),
  create: (projectId: string, input: MemoryInput) => request<MemoryRecord>(base(projectId), json("POST", input)),
  update: (projectId: string, ref: string, changes: MemoryChanges) => request<MemoryRecord>(one(projectId, ref), json("PATCH", changes)),
  supersede: (projectId: string, ref: string, input: MemoryReplacement) => request<MemoryRecord>(`${one(projectId, ref)}/supersede`, json("POST", input)),
  archive: (projectId: string, ref: string) => request<MemoryRecord>(`${one(projectId, ref)}/archive`, json("POST")),
  invalidate: (projectId: string, ref: string) => request<MemoryRecord>(`${one(projectId, ref)}/invalidate`, json("POST")),
  restore: (projectId: string, ref: string) => request<MemoryRecord>(`${one(projectId, ref)}/restore`, json("POST")),
  remove: (projectId: string, ref: string) => request<void>(one(projectId, ref), json("DELETE")),
  link: (projectId: string, ref: string, related: string) => request<MemoryRecord>(`${one(projectId, ref)}/links`, json("POST", { related })),
  unlink: (projectId: string, ref: string, related: string) => request<MemoryRecord>(`${one(projectId, ref)}/links/${encodeURIComponent(related)}`, json("DELETE")),
};

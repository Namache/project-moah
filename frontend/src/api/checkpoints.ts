import { ApiError, request } from "./client";
import type { Checkpoint, CheckpointChanges, CheckpointFilters, CheckpointInput } from "../types/checkpoint";

const base = (projectId: string) => `/projects/${encodeURIComponent(projectId)}/checkpoints`;
const one = (projectId: string, id: string) => `${base(projectId)}/${encodeURIComponent(id)}`;

function pathWithFilters(projectId: string, filters: CheckpointFilters): string {
  const params = new URLSearchParams();
  if (filters.task) params.set("task", filters.task);
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  if (filters.offset !== undefined) params.set("offset", String(filters.offset));
  const query = params.toString();
  return `${base(projectId)}${query ? `?${query}` : ""}`;
}

export const checkpointsApi = {
  list: (projectId: string, filters: CheckpointFilters = {}, signal?: AbortSignal) =>
    request<Checkpoint[]>(pathWithFilters(projectId, filters), { signal }),
  latest: async (projectId: string, task?: string, signal?: AbortSignal): Promise<Checkpoint | null> => {
    const params = task ? `?${new URLSearchParams({ task })}` : "";
    try {
      return await request<Checkpoint>(`${base(projectId)}/latest${params}`, { signal });
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }
  },
  get: (projectId: string, id: string, signal?: AbortSignal) =>
    request<Checkpoint>(one(projectId, id), { signal }),
  create: (projectId: string, input: CheckpointInput) =>
    request<Checkpoint>(base(projectId), { method: "POST", body: JSON.stringify(input) }),
  update: (projectId: string, id: string, changes: CheckpointChanges) =>
    request<Checkpoint>(one(projectId, id), { method: "PATCH", body: JSON.stringify(changes) }),
};

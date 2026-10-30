import { request } from "./client";

export interface Handoff { project_id: string; task: string | null; text: string; estimated_tokens: number; warnings: string[] }

export const handoffApi = {
  get: (projectId: string, task?: string | null) => request<Handoff>(`/projects/${encodeURIComponent(projectId)}/handoff${task ? `?task=${encodeURIComponent(task)}` : ""}`),
};

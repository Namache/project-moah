import type { Project, ProjectInput, ProjectUpdate } from "../types/project";
import { json, request } from "./client";

export const projectsApi = {
  list: (signal?: AbortSignal) => request<Project[]>("/projects?include_archived=true", { signal }),
  get: (id: string, signal?: AbortSignal) => request<Project>(`/projects/${encodeURIComponent(id)}`, { signal }),
  create: (project: ProjectInput) => request<Project>("/projects", json("POST", project)),
  update: (id: string, changes: ProjectUpdate) => request<Project>(`/projects/${encodeURIComponent(id)}`, json("PATCH", changes)),
  archive: (id: string) => request<Project>(`/projects/${encodeURIComponent(id)}/archive`, json("POST")),
};

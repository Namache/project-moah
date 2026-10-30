import { json, request } from "./client";
import type { CommitList, FileChanges, FileNotes, FileTree, GitStatus } from "../types/files";

const base = (projectId: string) => `/projects/${encodeURIComponent(projectId)}`;
const file = (projectId: string, id: string) => `${base(projectId)}/files/${encodeURIComponent(id)}`;

export const filesApi = {
  tree: (projectId: string, signal?: AbortSignal) => request<FileTree>(`${base(projectId)}/files/tree`, { signal }),
  get: (projectId: string, id: string, signal?: AbortSignal) => request<FileNotes>(file(projectId, id), { signal }),
  create: (projectId: string, path: string, changes: FileChanges = {}) => request<FileNotes>(`${base(projectId)}/files`, json("POST", { path, ...changes })),
  update: (projectId: string, id: string, changes: FileChanges) => request<FileNotes>(file(projectId, id), json("PATCH", changes)),
  reviewed: (projectId: string, id: string) => request<FileNotes>(`${file(projectId, id)}/reviewed`, json("POST")),
  remove: (projectId: string, id: string) => request<void>(file(projectId, id), json("DELETE")),
  history: (projectId: string, id: string, signal?: AbortSignal) => request<CommitList>(`${file(projectId, id)}/git`, { signal }),
  git: (projectId: string, signal?: AbortSignal) => request<GitStatus>(`${base(projectId)}/git`, { signal }),
  commits: (projectId: string, signal?: AbortSignal) => request<CommitList>(`${base(projectId)}/git/commits`, { signal }),
  linkCommit: (projectId: string, sha: string, task: string) => request<unknown>(`${base(projectId)}/git/commits/${encodeURIComponent(sha)}/tasks`, json("POST", { task })),
  unlinkCommit: (projectId: string, sha: string, task: string) => request<void>(`${base(projectId)}/git/commits/${encodeURIComponent(sha)}/tasks/${encodeURIComponent(task)}`, json("DELETE")),
};

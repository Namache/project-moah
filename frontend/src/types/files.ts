import type { MemoryRef } from "./memory";
import type { TaskRef } from "./task";

export type GitState = "ok" | "no_path" | "path_missing" | "not_shared" | "git_missing" | "not_repo" | "unsafe_repo" | "timeout" | "error";

export interface ChangedFile { path: string; status: string }
export interface GitStatus {
  state: GitState;
  message: string;
  root_path: string | null;
  branch: string | null;
  detached: boolean;
  head: string | null;
  head_subject: string | null;
  clean: boolean | null;
  changed: ChangedFile[];
  changed_total: number;
  warnings: string[];
}

export interface Symbol { id: string; name: string; kind: string; summary: string | null }
export interface SymbolInput { name: string; kind: string; summary?: string | null }
export interface FileNotes {
  id: string;
  project_id: string;
  path: string;
  language: string | null;
  purpose: string | null;
  summary: string | null;
  last_seen_hash: string | null;
  stale: boolean | null;
  symbols: Symbol[];
  tasks: TaskRef[];
  memories: MemoryRef[];
  checkpoints: { id: string; title: string }[];
}
export interface FileChanges {
  language?: string | null;
  purpose?: string | null;
  summary?: string | null;
  symbols?: SymbolInput[];
  task_ids?: string[];
  memory_ids?: string[];
  checkpoint_ids?: string[];
}
export interface FileTreeEntry { path: string; file_id: string | null; has_notes: boolean; stale: boolean | null; changed: string | null }
export interface FileTree { git: GitStatus; entries: FileTreeEntry[]; truncated: boolean; source: "git" | "folder" | "notes" }

export interface CommitTask { task: TaskRef; status: "confirmed" | "suggested"; origin: string }
export interface Commit { sha: string; short_sha: string; subject: string; author: string | null; committed_at: string | null; files: string[]; tasks: CommitTask[]; in_repository: boolean }
export interface CommitList { git: GitStatus; commits: Commit[] }

import type { TaskRef } from "./task";

export interface Checkpoint {
  id: string;
  project_id: string;
  task_id: string | null;
  task: TaskRef | null;
  title: string;
  summary: string;
  completed_work: string;
  remaining_work: string;
  problems: string;
  next_steps: string;
  agent: string | null;
  git_commit: string | null;
  created_at: string;
  updated_at: string;
}

export interface CheckpointInput {
  task_id?: string | null;
  title: string;
  summary?: string;
  completed_work?: string;
  remaining_work?: string;
  problems?: string;
  next_steps?: string;
  agent?: string | null;
  git_commit?: string | null;
}

export type CheckpointChanges = Partial<CheckpointInput>;

export interface CheckpointFilters {
  task?: string;
  limit?: number;
  offset?: number;
}

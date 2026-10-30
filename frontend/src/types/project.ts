export type ProjectStatus = "active" | "paused" | "completed" | "archived";

export interface Project {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  icon: string | null;
  accent: string | null;
  root_path: string | null;
  task_prefix?: string | null;
  status: ProjectStatus;
  current_focus_task_id: string | null;
  created_at: string;
  updated_at: string;
  last_opened_at: string | null;
  archived_at: string | null;
}

export interface ProjectInput {
  name: string;
  description?: string | null;
  icon?: string | null;
  accent?: string | null;
  root_path?: string | null;
}

export type ProjectUpdate = Partial<ProjectInput> & { status?: ProjectStatus };

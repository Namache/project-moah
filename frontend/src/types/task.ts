import type { ImageInfo } from "./image";
import { labels, msg } from "../lib/i18n";

export type TaskStatus = "backlog" | "todo" | "in_progress" | "blocked" | "review" | "completed" | "archived";
export type TaskPriority = "low" | "normal" | "high" | "critical";
export type MilestoneStatus = "planned" | "active" | "completed" | "archived";
export type RelationshipType = "parent" | "child" | "depends_on" | "blocks" | "related_to" | "supersedes" | "superseded_by";

export const boardColumns: { status: TaskStatus; label: string }[] = [
  labels({ status: "backlog", label: msg("Backlog") }, ["label"]),
  labels({ status: "todo", label: msg("To do") }, ["label"]),
  labels({ status: "in_progress", label: msg("In progress") }, ["label"]),
  labels({ status: "blocked", label: msg("Blocked") }, ["label"]),
  labels({ status: "review", label: msg("Review") }, ["label"]),
  labels({ status: "completed", label: msg("Done") }, ["label"]),
];

export const statusLabels: Record<TaskStatus, string> = labels({
  backlog: msg("Backlog"), todo: msg("To do"), in_progress: msg("In progress"), blocked: msg("Blocked"), review: msg("Review"), completed: msg("Done"), archived: msg("Archived"),
});
export const priorityLabels: Record<TaskPriority, string> = labels({ low: msg("Low"), normal: msg("Normal"), high: msg("High"), critical: msg("Critical") });

export interface Milestone {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  status: MilestoneStatus;
  target_date: string | null;
  sort_order: number;
  task_count: number;
  completed_task_count: number;
}

export type MilestoneChanges = Partial<Pick<Milestone, "name" | "description" | "status" | "target_date" | "sort_order">>;

export interface TaskSummary {
  id: string;
  project_id: string;
  milestone_id: string | null;
  human_id: string;
  title: string;
  status: TaskStatus;
  priority: TaskPriority;
  next_action: string | null;
  sort_order: number;
  criteria_total: number;
  criteria_completed: number;
  tags: string[];
  is_focus: boolean;
  is_blocked_by_open_dependency: boolean;
}

export interface Criterion { id: string; description: string; is_completed: boolean; sort_order: number }
export interface TaskRef { id: string; human_id: string; title: string; status: TaskStatus }
export interface Relationship { id: string; type: RelationshipType; task: TaskRef }

export interface TaskDetail extends TaskSummary {
  description: string | null;
  acceptance_criteria: Criterion[];
  relationships: Relationship[];
  milestone: Milestone | null;
  images?: ImageInfo[];
}

export interface WorkspaceTask extends TaskSummary {
  project_name: string;
  project_icon: string | null;
  project_accent: string | null;
}

export interface ProjectOverview {
  project_id: string;
  task_counts: Partial<Record<TaskStatus, number>>;
  focus_task: TaskSummary | null;
  active_milestone: Milestone | null;
}

export interface TaskInput {
  title: string;
  prefix?: string | null;
  status?: TaskStatus;
  priority?: TaskPriority;
  milestone_id?: string | null;
  next_action?: string | null;
  description?: string | null;
  acceptance_criteria?: string[];
  tags?: string[];
}

export type TaskUpdate = Partial<Pick<TaskDetail, "title" | "description" | "status" | "priority" | "milestone_id" | "next_action" | "tags">>;

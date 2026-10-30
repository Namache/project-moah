export type ActivityActor = "human" | "codex" | "claude" | "system";
export type ActivityEntityType = "project" | "task" | "memory" | "checkpoint" | "git";
export type ActivityFilter = "all" | "human" | "claude" | "codex" | "tasks" | "memory" | "git";

export interface ActivityEvent {
  id: string;
  project_id: string;
  project_name: string;
  event_type: string;
  actor_type: ActivityActor;
  actor_name: string | null;
  entity_type: ActivityEntityType | null;
  entity_id: string | null;
  task_id: string | null;
  metadata: Record<string, unknown>;
  timestamp: string;
}

export interface ActivityFilters {
  eventTypes?: string[];
  actorTypes?: ActivityActor[];
  entityTypes?: ActivityEntityType[];
  task?: string;
  projectId?: string;
  limit?: number;
  offset?: number;
}

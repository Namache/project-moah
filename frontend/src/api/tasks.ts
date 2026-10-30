import type { Project } from "../types/project";
import type { Milestone, MilestoneChanges, MilestoneStatus, ProjectOverview, RelationshipType, TaskDetail, TaskInput, TaskStatus, TaskSummary, TaskUpdate, WorkspaceTask } from "../types/task";
import { json, request } from "./client";

const base = (projectId: string) => `/projects/${encodeURIComponent(projectId)}`;
const taskUrl = (projectId: string, taskId: string) => `${base(projectId)}/tasks/${encodeURIComponent(taskId)}`;

export const tasksApi = {
  list: (projectId: string, signal?: AbortSignal) => request<TaskSummary[]>(`${base(projectId)}/tasks`, { signal }),
  listArchived: (projectId: string, signal?: AbortSignal) => request<TaskSummary[]>(`${base(projectId)}/tasks?status=archived`, { signal }),
  get: (projectId: string, taskId: string, signal?: AbortSignal) => request<TaskDetail>(taskUrl(projectId, taskId), { signal }),
  create: (projectId: string, input: TaskInput) => request<TaskDetail>(`${base(projectId)}/tasks`, json("POST", input)),
  update: (projectId: string, taskId: string, changes: TaskUpdate) => request<TaskDetail>(taskUrl(projectId, taskId), json("PATCH", changes)),
  move: (projectId: string, taskId: string, status: TaskStatus, index: number) => request<TaskDetail>(`${taskUrl(projectId, taskId)}/move`, json("POST", { status, index })),
  start: (projectId: string, taskId: string) => request<TaskDetail>(`${taskUrl(projectId, taskId)}/start`, json("POST")),
  remove: (projectId: string, taskId: string) => request<unknown>(taskUrl(projectId, taskId), json("DELETE")),
  addCriterion: (projectId: string, taskId: string, description: string) => request<TaskDetail>(`${taskUrl(projectId, taskId)}/criteria`, json("POST", { description })),
  updateCriterion: (projectId: string, taskId: string, criterionId: string, changes: { description?: string; is_completed?: boolean; sort_order?: number }) => request<TaskDetail>(`${taskUrl(projectId, taskId)}/criteria/${encodeURIComponent(criterionId)}`, json("PATCH", changes)),
  deleteCriterion: (projectId: string, taskId: string, criterionId: string) => request<TaskDetail>(`${taskUrl(projectId, taskId)}/criteria/${encodeURIComponent(criterionId)}`, json("DELETE")),
  addRelationship: (projectId: string, taskId: string, type: RelationshipType, target: string) => request<TaskDetail>(`${taskUrl(projectId, taskId)}/relationships`, json("POST", { type, target })),
  removeRelationship: (projectId: string, taskId: string, relationshipId: string) => request<TaskDetail>(`${taskUrl(projectId, taskId)}/relationships/${encodeURIComponent(relationshipId)}`, json("DELETE")),
  setFocus: (projectId: string, task: string | null) => request<Project>(`${base(projectId)}/focus`, json("PUT", { task })),
  milestones: (projectId: string, signal?: AbortSignal, includeArchived = false) => request<Milestone[]>(`${base(projectId)}/milestones${includeArchived ? "?include_archived=true" : ""}`, { signal }),
  createMilestone: (projectId: string, input: { name: string; status?: MilestoneStatus }) => request<Milestone>(`${base(projectId)}/milestones`, json("POST", input)),
  updateMilestone: (projectId: string, id: string, changes: MilestoneChanges) => request<Milestone>(`${base(projectId)}/milestones/${encodeURIComponent(id)}`, json("PATCH", changes)),
  overviews: (signal?: AbortSignal) => request<ProjectOverview[]>("/workspace/overviews", { signal }),
  workspaceTasks: (signal?: AbortSignal) => request<WorkspaceTask[]>("/tasks?limit=500", { signal }),
};

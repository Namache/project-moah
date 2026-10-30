import { request } from "./client";

export interface TaskSettings { auto_delete_done: boolean; auto_delete_done_since: string | null }

export const settingsApi = {
  tasks: (signal?: AbortSignal) => request<TaskSettings>("/settings/tasks", { signal }),
  updateTasks: (changes: Pick<TaskSettings, "auto_delete_done">) => request<TaskSettings>("/settings/tasks", { method: "PATCH", body: JSON.stringify(changes) }),
};

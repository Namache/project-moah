import { request } from "./client";

export type AgentName = "claude" | "codex";
export interface AgentSettings { default_agent: AgentName; second_opinion_enabled: boolean; codex_command: string; claude_command: string; update_check_enabled: boolean }
export interface WorkPrompt { agent: AgentName; task: string; prompt: string; url: string; folder: string | null }

export const agentsApi = {
  settings: (signal?: AbortSignal) => request<AgentSettings>("/settings/agents", { signal }),
  update: (changes: Partial<AgentSettings>) => request<AgentSettings>("/settings/agents", { method: "PATCH", body: JSON.stringify(changes) }),
  workPrompt: (projectId: string, task: string, agent?: AgentName) => request<WorkPrompt>(`/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(task)}/work-prompt${agent ? `?agent=${agent}` : ""}`),
};

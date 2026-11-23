import { request } from "./client";

export type AgentName = "claude" | "codex";
export interface AgentSettings { default_agent: AgentName; second_opinion_enabled: boolean; codex_command: string; claude_command: string; update_check_enabled: boolean; explore_packs: boolean; review_single_keys?: boolean }
export interface WorkPrompt { agent: AgentName; task: string; prompt: string; url: string; folder: string | null }
/**
 * Where a decision from Review goes (backend agent_prompts.chat_of). desktop: a Claude Code chat the Claude app knows, `url` opens it.
 * terminal: a Claude Code chat the app does not know. elsewhere: the app's records could not be read here. codex: a Codex chat,
 * `url` is its thread link and `resume` the command for a terminal. unknown: the review did not record its chat.
 */
export type ChatKind = "desktop" | "terminal" | "elsewhere" | "codex" | "unknown";
export interface ReviewChat { kind: ChatKind; agent: AgentName | null; url: string | null; delivered: boolean; resume: string | null }
/** The new-chat prompt (WorkPrompt) plus the chat that asked. */
export interface FixPrompt extends WorkPrompt { chat?: ReviewChat }

export const agentsApi = {
  settings: (signal?: AbortSignal) => request<AgentSettings>("/settings/agents", { signal }),
  update: (changes: Partial<AgentSettings>) => request<AgentSettings>("/settings/agents", { method: "PATCH", body: JSON.stringify(changes) }),
  workPrompt: (projectId: string, task: string, agent?: AgentName) => request<WorkPrompt>(`/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(task)}/work-prompt${agent ? `?agent=${agent}` : ""}`),
};

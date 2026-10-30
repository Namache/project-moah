import { request } from "./client";

export type FolderStatus = "created" | "linked" | "suggested" | "ignored";
export interface AgentFolder { folder: string; status: FolderStatus; project_id: string | null; project_name: string | null; claude_sessions: number; codex_sessions: number; last_seen: string | null }
export interface AgentFolders { created?: string[]; suggested?: string[]; folders: AgentFolder[] }

export const agentFoldersApi = {
  sync: (signal?: AbortSignal) => request<AgentFolders>("/agent-folders", { signal }),
  decide: (folder: string, action: "link" | "create" | "ignore", projectId?: string) => request<AgentFolders>("/agent-folders/decide", { method: "POST", body: JSON.stringify({ folder, action, project_id: projectId ?? null }) }),
};

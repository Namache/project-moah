import { t } from "../lib/i18n";
import { ApiError, authHeaders, request } from "./client";

export interface Diagnostics {
  app_version: string;
  python: string;
  platform: string;
  sqlite_version: string;
  database: { path: string | null; size_bytes: number | null; migration: string | null; integrity: string; foreign_key_problems: number; search_index_ready: boolean };
  counts: Record<string, number>;
  git: { available: boolean; version: string | null };
  mcp: { command: string; tools: number };
}

/** How agents start this installation's MCP server: the Flatpak, the .deb launcher, the Windows executable, or source. */
export interface AgentLaunch { install: "flatpak" | "deb" | "linux" | "windows" | "source"; command: string[] }

export const systemApi = {
  diagnostics: (signal?: AbortSignal) => request<Diagnostics>("/system/diagnostics", { signal }),
  agentCommand: (signal?: AbortSignal) => request<AgentLaunch>("/system/agent-command", { signal }),
  /** Fetches the backup with the app's own credentials, then hands it to the system's save flow. */
  async downloadBackup(): Promise<string> {
    const response = await fetch("/api/system/export", { headers: authHeaders() });
    if (!response.ok) throw new ApiError(t("The backup could not be created. Please try again."), response.status);
    const name = /filename="?([^";]+)"?/.exec(response.headers.get("content-disposition") ?? "")?.[1] ?? "project-moah-backup.db";
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
    return name;
  },
};

import { t } from "../lib/i18n";
import { ApiError, authHeaders, json, request } from "./client";
import type { DictationStatus } from "./dictation";

export interface Diagnostics {
  app_version: string;
  python: string;
  platform: string;
  sqlite_version: string;
  database: { path: string | null; size_bytes: number | null; migration: string | null; integrity: string; foreign_key_problems: number; search_index_ready: boolean };
  counts: Record<string, number>;
  git: { available: boolean; version: string | null };
  mcp: { command: string; tools: number };
  /** Packs served in the last day by each build; old ones mean an agent session still runs a build from before the last update. */
  builds?: { installed: string; last_day: Record<string, number>; old_build_last_day: number };
  /** How many entries the local error log holds: counts and a time, never the messages. */
  errors?: { total: number; last_day: number; last: string | null };
  /** Whether dictation works here and how the speech engine did lately: times, never words. */
  dictation?: DictationStatus;
}

/** Where an error happened: the local service, an agent's MCP server, the desktop app, or the app window. */
export type ErrorSource = "service" | "mcp" | "desktop" | "window";
export interface ErrorEntry { time: string; source: ErrorSource; level: "error" | "warning"; message: string; detail: string }
export interface ErrorLog { total: number; entries: ErrorEntry[] }

/** How agents start this installation's MCP server: the Flatpak, the .deb launcher, the Windows executable, or source. */
export interface AgentLaunch { install: "flatpak" | "deb" | "linux" | "windows" | "source"; command: string[] }

export interface AgentConnection { agent: "claude" | "codex"; status: "connected" | "not_found" | "failed"; detail: string }

/** Whether Project Moah was updated while the window was open. */
export interface UpdateStatus { running: string; newer: boolean; installed: string | null }

export const DIAGNOSTICS_TIMEOUT_MS = 30_000;

export const systemApi = {
  /** A check that takes too long ends with a message and a Retry button instead of "Checking…" for good. */
  async diagnostics(signal?: AbortSignal): Promise<Diagnostics> {
    const limit = new AbortController();
    let expired = false;
    const timer = setTimeout(() => { expired = true; limit.abort(); }, DIAGNOSTICS_TIMEOUT_MS);
    const forward = () => limit.abort();
    signal?.addEventListener("abort", forward);
    try {
      return await request<Diagnostics>("/system/diagnostics", { signal: limit.signal });
    } catch (error) {
      if (expired) throw new ApiError(t("The check took too long. Try again, or restart Project Moah if it keeps happening."), 0);
      throw error;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", forward);
    }
  },
  agentCommand: (signal?: AbortSignal) => request<AgentLaunch>("/system/agent-command", { signal }),
  update: (signal?: AbortSignal) => request<UpdateStatus>("/system/update", { signal }),
  errors: (signal?: AbortSignal) => request<ErrorLog>("/system/errors", { signal }),
  reportError: (message: string, detail: string) => request<void>("/system/errors", json("POST", { message, detail })),
  clearErrors: () => request<void>("/system/errors", { method: "DELETE" }),
  connectAgents: () => request<{ results: AgentConnection[] }>("/system/connect-agents", { method: "POST" }),
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

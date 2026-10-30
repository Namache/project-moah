export type Agent = "claude" | "codex";

export interface UsageTotals {
  fresh_tokens: number;
  cached_tokens: number;
  output_tokens: number;
  active_seconds: number;
  sessions: number;
}

export interface UsageRow extends UsageTotals {
  project_id: string | null;
  name: string;
}

export interface LimitWindow {
  used_percent: number;
  window_minutes: number;
  resets_at: string | null;
}

export interface SeriesPoint { start: string; claude: { fresh_tokens: number; active_seconds: number; sessions: number }; codex: { fresh_tokens: number; active_seconds: number; sessions: number } }
export interface ModelRow { agent: Agent; model: string; fresh_tokens: number; cached_tokens: number; replies: number }
export interface ToolRow { agent: Agent; tool: string; calls: number; output_chars: number }
export interface SessionRow { agent: Agent; session: string; project: string; project_id: string | null; fresh_tokens: number; active_seconds: number; replies: number; compactions: number; models: string[]; last_at: string }
export interface UsageSignals { opus_reply_share: number; compactions: Record<Agent, number>; subagents_started: Record<Agent, number>; tool_calls: Record<Agent, number>; tool_output_chars: Record<Agent, number> }

export interface UsageReport {
  generated_at: string;
  since: string;
  sources: Record<Agent, { found: boolean }>;
  totals: UsageTotals;
  by_agent: Record<Agent, UsageTotals>;
  hourly: ({ hour: string } & Record<Agent, number>)[];
  projects: UsageRow[];
  other_folders: UsageRow[];
  longest_session_seconds: number;
  until?: string;
  agent?: Agent | null;
  bucket?: "hour" | "day";
  series?: SeriesPoint[];
  by_model?: ModelRow[];
  by_tool?: ToolRow[];
  sessions?: SessionRow[];
  signals?: UsageSignals;
  codex_limits: ({ short?: LimitWindow; weekly?: LimitWindow; updated_at: string }) | null;
}

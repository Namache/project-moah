import type { UsageReport } from "../types/usage";

const hour = (hoursAgo: number) => { const d = new Date(); d.setMinutes(0, 0, 0); d.setHours(d.getHours() - hoursAgo); return d.toISOString(); };
const row = (project_id: string | null, name: string, fresh: number, cached: number, seconds: number) => ({ project_id, name, fresh_tokens: fresh, cached_tokens: cached, output_tokens: fresh / 10, active_seconds: seconds, sessions: 2 });

export function usageReport(overrides: Partial<UsageReport> = {}): UsageReport {
  const since = new Date(); since.setHours(0, 0, 0, 0); since.setDate(since.getDate() - 6);
  return {
    generated_at: new Date().toISOString(),
    since: since.toISOString(),
    sources: { claude: { found: true }, codex: { found: true } },
    totals: { fresh_tokens: 7_900_000, cached_tokens: 390_000_000, output_tokens: 900_000, active_seconds: 41 * 3600, sessions: 12 },
    by_agent: {
      claude: { fresh_tokens: 4_800_000, cached_tokens: 300_000_000, output_tokens: 600_000, active_seconds: 30 * 3600, sessions: 5 },
      codex: { fresh_tokens: 3_100_000, cached_tokens: 90_000_000, output_tokens: 300_000, active_seconds: 11 * 3600, sessions: 7 },
    },
    hourly: [{ hour: hour(30), claude: 1_000_000, codex: 200_000 }, { hour: hour(1), claude: 3_800_000, codex: 2_900_000 }],
    projects: [row("p1", "Trailhead", 4_700_000, 300_000_000, 31 * 3600)],
    other_folders: [row(null, "~/Desktop/Scratch", 1_100_000, 20_000_000, 4 * 3600)],
    longest_session_seconds: 6 * 3600,
    codex_limits: {
      short: { used_percent: 82, window_minutes: 300, resets_at: new Date(Date.now() + 3_600_000).toISOString() },
      weekly: { used_percent: 30, window_minutes: 10080, resets_at: new Date(Date.now() - 60_000).toISOString() },
      updated_at: new Date().toISOString(),
    },
    series: Array.from({ length: 7 }, (_, i) => { const d = new Date(since); d.setDate(d.getDate() + i); return { start: d.toISOString(), claude: { fresh_tokens: i === 6 ? 3_800_000 : 100_000, active_seconds: 3600, sessions: 1 }, codex: { fresh_tokens: i === 6 ? 2_900_000 : 50_000, active_seconds: 1800, sessions: 1 } }; }),
    by_model: [{ agent: "claude", model: "claude-opus-5-5", fresh_tokens: 4_600_000, cached_tokens: 1, replies: 900 }, { agent: "codex", model: "gpt-6-astra", fresh_tokens: 3_100_000, cached_tokens: 1, replies: 300 }],
    by_tool: [{ agent: "claude", tool: "Bash", calls: 1520, output_chars: 3_100_000 }, { agent: "claude", tool: "Read", calls: 560, output_chars: 900_000 }, { agent: "codex", tool: "exec", calls: 270, output_chars: 800_000 }],
    sessions: [{ agent: "codex", session: "abc", project: "Trailhead", project_id: "p1", fresh_tokens: 2_000_000, active_seconds: 7200, replies: 80, compactions: 3, models: ["gpt-6-astra"], last_at: new Date().toISOString() }],
    signals: { opus_reply_share: 0.96, compactions: { claude: 1, codex: 24 }, subagents_started: { claude: 2, codex: 3 }, tool_calls: { claude: 2080, codex: 270 }, tool_output_chars: { claude: 4_000_000, codex: 800_000 } },
    ...overrides,
  };
}

import { Clock, Gauge, Lightbulb, Recycle, Zap } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { pickTips, TIP_SOURCES } from "../../content/efficiency-tips";
import { useUsage, useUsageSlice, type AgentFilter, type UsageRange } from "../../hooks/useUsage";
import { UsageBreakdown } from "./UsageBreakdown";
import type { LimitWindow, UsageReport, UsageRow } from "../../types/usage";
import { readPref, writePref } from "../../lib/prefs";
import { ErrorState, LoadingState } from "../ui";
import { AGENT_COLORS, formatDuration, formatTokens, UsageChart } from "./UsageChart";
import { projectPath } from "../../lib/routes";

const RANGES: { value: UsageRange; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
];
const RANGE_KEY = "pb-usage-range";
const AGENT_KEY = "pb-usage-agent";
const AGENT_FILTERS: { value: AgentFilter; label: string }[] = [{ value: "both", label: "Both" }, { value: "claude", label: "Claude" }, { value: "codex", label: "Codex" }];
const sliceLabel = (start: string, hourly: boolean) => { const at = new Date(start); return hourly ? `${String(at.getHours()).padStart(2, "0")}:00 to ${String((at.getHours() + 1) % 24).padStart(2, "0")}:00` : at.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" }); };

function reuse(cached: number, fresh: number): string {
  const total = cached + fresh;
  return total > 0 ? `${Math.round((cached / total) * 100)}%` : "None yet";
}

function Tile({ icon, label, value, children }: { icon: ReactNode; label: string; value: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-5 shadow-card">
      <p className="flex items-center gap-2 text-xs font-semibold text-ink-muted"><span className="text-forest" aria-hidden="true">{icon}</span>{label}</p>
      <p className="mt-2 text-3xl font-semibold tracking-tight text-ink tabular-nums">{value}</p>
      {children && <div className="mt-2 text-xs leading-5 text-ink-subtle">{children}</div>}
    </div>
  );
}

/** A window whose reset time has passed is shown as reset, not with its stale percentage. */
function LimitBar({ label, window }: { label: string; window: LimitWindow | undefined }) {
  if (!window) return null;
  const reset = window.resets_at ? new Date(window.resets_at) : null;
  const expired = reset !== null && reset.getTime() < Date.now();
  const used = expired ? 0 : Math.min(100, Math.max(0, window.used_percent));
  const when = reset && !expired ? reset.toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" }) : null;
  const tone = used >= 90 ? "bg-danger-solid" : used >= 75 ? "bg-warning" : "bg-primary";
  return (
    <div className="mt-2">
      <div className="flex justify-between gap-2"><span>{label}</span><span className="font-semibold text-ink tabular-nums">{expired ? "Reset" : `${Math.round(used)}% used`}</span></div>
      <div className="mt-1 h-2 overflow-hidden rounded-full bg-sage-pale" role="meter" aria-label={`Codex ${label.toLowerCase()} limit`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(used)}>
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${used}%` }} />
      </div>
      {when && <p className="mt-0.5">Resets {when}</p>}
    </div>
  );
}

function UsageTable({ rows, other }: { rows: UsageRow[]; other: UsageRow[] }) {
  if (!rows.length && !other.length) return <p className="text-sm text-ink-muted">No agent work in this range yet.</p>;
  const cell = "px-2 py-2.5 text-right tabular-nums";
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] text-sm">
        <thead className="text-xs text-ink-subtle"><tr className="border-b border-line">
          <th className="py-2 pr-2 text-left font-semibold">Project or folder</th><th className="px-2 py-2 text-right font-semibold">Fresh tokens</th><th className="px-2 py-2 text-right font-semibold">Active time</th><th className="px-2 py-2 text-right font-semibold">Cache reuse</th><th className="py-2 pl-2 text-right font-semibold">Tokens per hour</th>
        </tr></thead>
        <tbody>
          {[...rows, ...other].map((row) => (
            <tr key={row.project_id ?? row.name} className="border-b border-line last:border-0">
              <td className="max-w-[16rem] truncate py-2.5 pr-2" title={row.name}>
                {row.project_id ? <Link to={projectPath(row.project_id)} className="font-semibold text-ink hover:text-forest focus-visible:outline-2 focus-visible:outline-forest">{row.name}</Link>
                  : <span className="text-ink-muted">{row.name}<span className="ml-2 rounded-full bg-canvas px-2 py-0.5 text-xs text-ink-subtle">No project</span></span>}
              </td>
              <td className={cell}>{formatTokens(row.fresh_tokens)}</td>
              <td className={cell}>{formatDuration(row.active_seconds)}</td>
              <td className={cell}>{reuse(row.cached_tokens, row.fresh_tokens)}</td>
              <td className="py-2.5 pl-2 text-right tabular-nums">{row.active_seconds >= 60 ? formatTokens(row.fresh_tokens / (row.active_seconds / 3600)) : "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {other.length > 0 && <p className="mt-3 text-xs text-ink-subtle">Folders marked "No project" are not inside any project's repository folder. To count them, set the project's repository folder with Edit on its page. <Link to="/projects" className="font-semibold text-forest hover:underline">Projects</Link></p>}
    </div>
  );
}

const HIDDEN_KEY = "pb-hidden-tips";
function readHidden(): Set<string> {
  try { return new Set(JSON.parse(readPref(HIDDEN_KEY) ?? "[]") as string[]); } catch { return new Set(); }
}

function Tips({ report }: { report: UsageReport }) {
  const [all, setAll] = useState(false);
  const [hidden, setHidden] = useState(readHidden);
  const hide = (id: string) => setHidden((current) => { const next = new Set(current).add(id); writePref(HIDDEN_KEY, JSON.stringify([...next])); return next; });
  const restore = () => { writePref(HIDDEN_KEY, null); setHidden(new Set()); };
  const tips = pickTips(report, all ? 20 : 4, hidden);
  return (
    <section aria-labelledby="tips-title" className="rounded-xl border border-line bg-surface p-5 shadow-card">
      <h2 id="tips-title" className="flex items-center gap-2 text-base font-semibold text-ink"><Lightbulb size={17} className="text-forest" aria-hidden="true" />Tips for you</h2>
      <ul className="mt-2 divide-y divide-line">
        {tips.map((tip) => (
          <li key={tip.id} className="py-3">
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm font-semibold text-ink">{tip.title}</p>
              <button type="button" onClick={() => hide(tip.id)} className="flex-none rounded px-1.5 text-xs text-ink-subtle hover:bg-canvas hover:text-ink" aria-label={`Hide the tip: ${tip.title}`}>Hide</button>
            </div>
            {tip.evidence?.(report) && <p className="mt-1 rounded-lg bg-canvas px-2.5 py-1.5 text-xs font-medium text-ink">{tip.evidence(report)}</p>}
            <p className="mt-1 text-sm leading-5 text-ink-muted">{tip.body}</p>
            <p className="mt-1.5 flex flex-wrap gap-1.5">{tip.sources.map((source) => <span key={source} title={TIP_SOURCES[source].url} className="inline-flex items-center gap-1.5 rounded-full bg-hover px-2 py-0.5 text-xs font-semibold text-ink-muted"><span className="h-1.5 w-1.5 rounded-full" style={{ background: AGENT_COLORS[source === "claude" ? "claude" : "codex"] }} aria-hidden="true" />{TIP_SOURCES[source].label}</span>)}</p>
          </li>
        ))}
      </ul>
      <div className="mt-1 flex flex-wrap gap-4">
        <button type="button" onClick={() => setAll((v) => !v)} className="text-sm font-semibold text-forest hover:underline focus-visible:outline-2 focus-visible:outline-forest">{all ? "Show fewer tips" : "Show all tips"}</button>
        {hidden.size > 0 && <button type="button" onClick={restore} className="text-sm text-ink-muted hover:underline">Show {hidden.size} hidden {hidden.size === 1 ? "tip" : "tips"}</button>}
      </div>
    </section>
  );
}

export function EfficiencyDashboard() {
  const [range, setRangeState] = useState<UsageRange>(() => {
    const saved = readPref(RANGE_KEY);
    return saved === "today" || saved === "30d" ? saved : "7d";
  });
  const setRange = (value: UsageRange) => { setRangeState(value); setSelected(null); writePref(RANGE_KEY, value); };
  const [agent, setAgentState] = useState<AgentFilter>(() => { const saved = readPref(AGENT_KEY); return saved === "claude" || saved === "codex" ? saved : "both"; });
  const [selected, setSelected] = useState<string | null>(null);
  const setAgent = (value: AgentFilter) => { setAgentState(value); setSelected(null); writePref(AGENT_KEY, value); };
  const usage = useUsage(range, agent);
  const slice = useUsageSlice(selected, range === "today", agent);
  const report = usage.data && typeof usage.data === "object" && "totals" in usage.data ? usage.data : null;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">Usage</h1>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 text-sm text-ink-muted">
            <span>Claude Code and Codex on this computer, from their local logs</span>
            {report && <span className="inline-flex items-center gap-1.5 text-xs" aria-live="off"><span className={`h-2 w-2 rounded-full ${usage.isError ? "bg-warning" : "bg-success"}`} aria-hidden="true" />{usage.isError ? "Paused, retrying" : "Live"}, updated {new Date(report.generated_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div role="group" aria-label="Agent" className="segmented">
            {AGENT_FILTERS.map(({ value, label }) => <button key={value} type="button" aria-pressed={agent === value} onClick={() => setAgent(value)} className={`filter-tab flex items-center gap-1.5 ${agent === value ? "filter-tab-active" : ""}`}>{value !== "both" && <span className="inline-block h-2 w-2 rounded-full" style={{ background: AGENT_COLORS[value] }} aria-hidden="true" />}{label}</button>)}
          </div>
          <div role="group" aria-label="Time range" className="segmented">
            {RANGES.map(({ value, label }) => <button key={value} type="button" aria-pressed={range === value} onClick={() => setRange(value)} className={`filter-tab ${range === value ? "filter-tab-active" : ""}`}>{label}</button>)}
          </div>
        </div>
      </div>

      {!report ? (usage.isError ? <ErrorState title="Usage is unavailable" message={usage.error.message} onRetry={() => void usage.refetch()} /> : <LoadingState label="Reading Claude Code and Codex logs" />) : (
        <>
          {(!report.sources.claude.found || !report.sources.codex.found) && (
            <p className="rounded-xl border border-line bg-surface px-4 py-3 text-sm text-ink-muted">
              {!report.sources.claude.found && "Claude Code logs were not found (~/.claude/projects). "}
              {!report.sources.codex.found && "Codex logs were not found (~/.codex/sessions). "}
              If the agent is installed, Project Moah may need permission to read that folder; see Help.
            </p>
          )}
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Tile icon={<Zap size={15} />} label="Fresh tokens" value={formatTokens(report.totals.fresh_tokens)}>
              <span className="flex flex-wrap gap-x-4">{(["claude", "codex"] as const).map((agent) => <span key={agent} className="flex items-center gap-1.5"><span className="inline-block h-2 w-2 rounded-full" style={{ background: AGENT_COLORS[agent] }} aria-hidden="true" />{agent === "claude" ? "Claude" : "Codex"} {formatTokens(report.by_agent[agent].fresh_tokens)}</span>)}</span>
              New input and output. Cached rereads are counted separately.
            </Tile>
            <Tile icon={<Recycle size={15} />} label="Cache reuse" value={reuse(report.totals.cached_tokens, report.totals.fresh_tokens)}>
              {formatTokens(report.totals.cached_tokens)} tokens reread from cache, which costs much less than fresh input.
            </Tile>
            <Tile icon={<Clock size={15} />} label="Active time" value={formatDuration(report.totals.active_seconds)}>
              Time with agent activity across {report.totals.sessions} {report.totals.sessions === 1 ? "session" : "sessions"}. Gaps over 5 minutes are not counted.
            </Tile>
            <Tile icon={<Gauge size={15} />} label="Codex limits" value={report.codex_limits?.short ? `${Math.round(report.codex_limits.short.resets_at && new Date(report.codex_limits.short.resets_at).getTime() < Date.now() ? 0 : report.codex_limits.short.used_percent)}%` : "No data"}>
              {report.codex_limits ? <><LimitBar label="5 hour window" window={report.codex_limits.short} /><LimitBar label="Weekly" window={report.codex_limits.weekly} /></> : "Codex reports its limits after its next reply."}
            </Tile>
          </div>
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.7fr)_minmax(300px,1fr)]">
            <section aria-label="Usage over time and by project" className="space-y-6 rounded-xl border border-line bg-surface p-5 shadow-card">
              <UsageChart report={report} byHour={range === "today"} selected={selected} onSelect={setSelected} />
              <div>
                <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                  <h2 className="text-base font-semibold text-ink">Where the work went</h2>
                  {selected && <button type="button" onClick={() => setSelected(null)} className="text-sm font-semibold text-forest hover:underline">Show the whole range</button>}
                </div>
                {selected && !slice.data ? <p role="status" className="py-3 text-sm text-ink-muted">{slice.isError ? `That ${range === "today" ? "hour" : "day"} could not be loaded.` : "Loading…"}</p>
                  : <UsageBreakdown report={selected && slice.data ? slice.data : report} caption={`${selected ? sliceLabel(selected, range === "today") : RANGES.find((r) => r.value === range)!.label}, ${agent === "both" ? "both agents" : agent === "claude" ? "Claude only" : "Codex only"}.`} projects={<UsageTable rows={(selected && slice.data ? slice.data : report).projects ?? []} other={(selected && slice.data ? slice.data : report).other_folders ?? []} />} />}
              </div>
            </section>
            <Tips report={report} />
          </div>
          <p className="text-xs leading-5 text-ink-subtle">Only token counts, times, model and tool names, folder paths and the size of tool output are read. Message and tool text is never stored. Claude's plan limits are not written to its local logs; run /usage in Claude Code to see them. Chats on claude.ai and in the Claude desktop Chat tab are not included.</p>
        </>
      )}
    </div>
  );
}

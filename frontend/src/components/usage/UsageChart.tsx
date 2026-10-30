import { useMemo, useState } from "react";
import type { Agent, UsageReport } from "../../types/usage";

// Validated categorical pair (dataviz validator, light surface): every check passes, CVD ΔE 24.7.
export const AGENT_COLORS: Record<Agent, string> = { claude: "#eb6834", codex: "#2a78d6" };
export const AGENT_LABELS: Record<Agent, string> = { claude: "Claude", codex: "Codex" };
const AGENTS: Agent[] = ["claude", "codex"];

export function formatTokens(value: number): string {
  if (value >= 1e9) return `${(value / 1e9).toFixed(value >= 1e10 ? 0 : 1)}B`;
  if (value >= 1e6) return `${(value / 1e6).toFixed(value >= 1e7 ? 0 : 1)}M`;
  if (value >= 1e3) return `${Math.round(value / 1e3)}k`;
  return String(Math.round(value));
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return seconds > 0 ? "under 1 min" : "0 min";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  const hours = seconds / 3600;
  return `${hours < 10 ? hours.toFixed(1).replace(/\.0$/, "") : Math.round(hours)} h`;
}

interface Bucket { key: string; label: string; claude: number; codex: number }

/** Hourly service buckets regrouped on the person's clock: by hour for today, by day otherwise. */
export function bucketize(report: UsageReport, byHour: boolean, now = new Date()): Bucket[] {
  const buckets = new Map<string, Bucket>();
  const start = new Date(report.since);
  const cursor = new Date(start);
  while (cursor <= now) {
    const key = byHour ? `${cursor.toDateString()} ${cursor.getHours()}` : cursor.toDateString();
    if (!buckets.has(key)) {
      const label = byHour ? `${String(cursor.getHours()).padStart(2, "0")}:00` : cursor.toLocaleDateString(undefined, { day: "numeric", month: "short" });
      buckets.set(key, { key, label, claude: 0, codex: 0 });
    }
    if (byHour) cursor.setHours(cursor.getHours() + 1);
    else cursor.setDate(cursor.getDate() + 1);
  }
  for (const row of report.hourly ?? []) {
    const at = new Date(row.hour);
    const bucket = buckets.get(byHour ? `${at.toDateString()} ${at.getHours()}` : at.toDateString());
    if (!bucket) continue;
    bucket.claude += row.claude ?? 0;
    bucket.codex += row.codex ?? 0;
  }
  return [...buckets.values()];
}

export type ChartMetric = "fresh_tokens" | "active_seconds" | "sessions";
const METRICS: { value: ChartMetric; label: string }[] = [
  { value: "fresh_tokens", label: "Tokens" },
  { value: "active_seconds", label: "Active time" },
  { value: "sessions", label: "Sessions" },
];
const formatMetric = (metric: ChartMetric, value: number) => metric === "fresh_tokens" ? formatTokens(value) : metric === "active_seconds" ? formatDuration(value) : String(value);

interface Point { key: string; start: string | null; label: string; claude: number; codex: number; detail: Record<Agent, { fresh_tokens: number; active_seconds: number; sessions: number }> | null }

function points(report: UsageReport, byHour: boolean, metric: ChartMetric): Point[] {
  if (report.series?.length) {
    return report.series.map((p) => {
      const at = new Date(p.start);
      return { key: p.start, start: p.start, label: byHour ? `${String(at.getHours()).padStart(2, "0")}:00` : at.toLocaleDateString(undefined, { day: "numeric", month: "short" }), claude: p.claude[metric], codex: p.codex[metric], detail: { claude: p.claude, codex: p.codex } };
    });
  }
  return bucketize(report, byHour).map((b) => ({ key: b.key, start: null, label: b.label, claude: metric === "fresh_tokens" ? b.claude : 0, codex: metric === "fresh_tokens" ? b.codex : 0, detail: null }));
}

export function UsageChart({ report, byHour, selected = null, onSelect }: { report: UsageReport; byHour: boolean; selected?: string | null; onSelect?: (start: string | null) => void }) {
  const [metric, setMetric] = useState<ChartMetric>("fresh_tokens");
  const data = useMemo(() => points(report, byHour, metric), [report, byHour, metric]);
  const [hover, setHover] = useState<number | null>(null);
  const [asTable, setAsTable] = useState(false);
  const shown = AGENTS.filter((a) => !report.agent || report.agent === a);
  const max = Math.max(1, ...data.map((b) => shown.reduce((sum, a) => sum + b[a], 0)));
  const labelEvery = Math.ceil(data.length / 10);
  const unit = METRICS.find((m) => m.value === metric)!.label;
  const title = `${unit} per ${byHour ? "hour" : "day"}`;

  return (
    <figure className="m-0">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <figcaption className="text-base font-semibold text-ink">{title}</figcaption>
        <div className="flex flex-wrap items-center gap-3 text-xs text-ink-muted">
          <div role="group" aria-label="Chart shows" className="flex rounded-lg border border-line p-0.5">
            {METRICS.map((m) => <button key={m.value} type="button" aria-pressed={metric === m.value} onClick={() => setMetric(m.value)} className={`rounded-md px-2.5 py-1 font-semibold ${metric === m.value ? "bg-sage-pale text-forest" : "hover:bg-canvas"}`}>{m.label}</button>)}
          </div>
          {shown.map((agent) => <span key={agent} className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: AGENT_COLORS[agent] }} aria-hidden="true" />{AGENT_LABELS[agent]}</span>)}
          <button type="button" className="rounded-md px-2 py-1 font-semibold text-forest hover:bg-sage-pale focus-visible:outline-2 focus-visible:outline-forest" onClick={() => setAsTable((v) => !v)} aria-pressed={asTable}>{asTable ? "Show chart" : "Show table"}</button>
        </div>
      </div>
      {asTable ? (
        <div className="max-h-56 overflow-auto rounded-xl border border-line">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-surface text-xs text-ink-subtle"><tr><th className="px-3 py-2 font-semibold">{byHour ? "Hour" : "Day"}</th>{shown.map((a) => <th key={a} className="px-3 py-2 text-right font-semibold">{AGENT_LABELS[a]}</th>)}</tr></thead>
            <tbody>{data.map((b) => <tr key={b.key} className="border-t border-line"><td className="px-3 py-1.5">{b.label}</td>{shown.map((a) => <td key={a} className="px-3 py-1.5 text-right tabular-nums">{formatMetric(metric, b[a])}</td>)}</tr>)}</tbody>
          </table>
        </div>
      ) : (
        <div className="relative" onMouseLeave={() => setHover(null)}>
          <div className="flex h-44 items-end gap-[2px] border-b border-line" role="group" aria-label={`${title}. Choose ${byHour ? "an hour" : "a day"} to see its breakdown below.`}>
            {data.map((b, index) => {
              const total = shown.reduce((sum, a) => sum + b[a], 0);
              const isSelected = selected !== null && b.start === selected;
              const dimmed = (hover !== null && hover !== index) || (selected !== null && !isSelected);
              return (
                <button key={b.key} type="button" disabled={!onSelect || !b.start} aria-pressed={isSelected} aria-label={`${b.label}: ${shown.map((a) => `${AGENT_LABELS[a]} ${formatMetric(metric, b[a])}`).join(", ")}`}
                  className={`flex h-full min-w-0 flex-1 flex-col justify-end rounded-t px-[1px] focus-visible:outline-2 focus-visible:outline-forest ${onSelect && b.start ? "cursor-pointer" : "cursor-default"} ${isSelected ? "bg-sage-pale" : ""}`}
                  onMouseEnter={() => setHover(index)} onFocus={() => setHover(index)} onBlur={() => setHover(null)} onClick={() => onSelect?.(isSelected ? null : b.start)}>
                  <span className={`flex flex-col-reverse gap-[2px] transition-opacity ${dimmed ? "opacity-50" : "opacity-100"}`} style={{ height: `${(total / max) * 100}%` }}>
                    {shown.map((agent, i) => b[agent] > 0 && <span key={agent} style={{ flexGrow: b[agent], background: AGENT_COLORS[agent], minHeight: 2 }} className={i === shown.length - 1 || !b[shown[i + 1]] ? "block rounded-t" : "block"} />)}
                  </span>
                </button>
              );
            })}
          </div>
          <div className="mt-1.5 flex gap-[2px] text-xs text-ink-subtle" aria-hidden="true">
            {data.map((b, index) => <span key={b.key} className="min-w-0 flex-1 truncate text-center">{index % labelEvery === 0 ? b.label : ""}</span>)}
          </div>
          {hover !== null && data[hover] && (
            <div className="pointer-events-none absolute top-0 z-10 w-48 rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-card-hover" style={{ left: `min(calc(${((hover + 0.5) / data.length) * 100}% + 8px), calc(100% - 12rem))` }}>
              <p className="font-semibold text-ink">{data[hover].label}</p>
              {shown.map((agent) => { const d = data[hover].detail?.[agent]; return (
                <div key={agent} className="mt-1">
                  <p className="flex items-center gap-1.5 font-semibold text-ink"><span className="inline-block h-2 w-2 rounded-sm" style={{ background: AGENT_COLORS[agent] }} />{AGENT_LABELS[agent]}</p>
                  {d ? <p className="text-ink-muted">{formatTokens(d.fresh_tokens)} tokens, {formatDuration(d.active_seconds)}, {d.sessions} {d.sessions === 1 ? "session" : "sessions"}</p> : <p className="text-ink-muted">{formatTokens(data[hover][agent])} tokens</p>}
                </div>
              ); })}
              {onSelect && data[hover].start && <p className="mt-1.5 text-ink-subtle">{selected === data[hover].start ? "Click to clear" : "Click for the breakdown"}</p>}
            </div>
          )}
        </div>
      )}
    </figure>
  );
}

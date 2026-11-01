import { useId, useState } from "react";
import { Link } from "react-router-dom";
import type { Agent, UsageReport } from "../../types/usage";
import { AGENT_COLORS, AGENT_LABELS, formatDuration, formatTokens } from "./UsageChart";
import { projectPath, taskPath } from "../../lib/routes";
import { labels, locale, msg, t, tp } from "../../lib/i18n";

type Tab = "model" | "tool" | "project" | "session" | "task" | "estimate";
const TABS: { value: Tab; label: string }[] = [labels({ value: "model", label: msg("By model") }, ["label"]), labels({ value: "tool", label: msg("By tool") }, ["label"]), labels({ value: "project", label: msg("By project") }, ["label"]), labels({ value: "session", label: msg("By session") }, ["label"]), labels({ value: "task", label: msg("By task") }, ["label"]), labels({ value: "estimate", label: msg("Pack estimates") }, ["label"])];

// Friendlier names for the tools that come up most.
const TOOL_NAMES: Record<string, string> = labels({ Bash: msg("Terminal commands"), Read: msg("Reading files"), Write: msg("Writing files"), Edit: msg("Editing files"), exec: msg("Terminal commands"), Agent: msg("Subagents"), Task: msg("Subagents"), spawn_agent: msg("Subagents started"), send_message: msg("Messages to subagents"), WebFetch: msg("Fetching web pages"), WebSearch: msg("Web searches"), Grep: msg("Searching code"), Glob: msg("Finding files") });
const prettyModel = (m: string) => m.replace(/^claude-/, "Claude ").replace(/^gpt-/, "GPT-").replace(/-(\d+)-(\d+)$/, " $1.$2").replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const chars = (n: number) => { const f = new Intl.NumberFormat(locale(), { maximumFractionDigits: 1 }); return n >= 1e6 ? t("{n}M chars", { n: f.format(n / 1e6) }) : n >= 1e3 ? t("{n}k chars", { n: f.format(Math.round(n / 1e3)) }) : t("{n} chars", { n: f.format(n) }); };

function Row({ agent, label, value, share, sub, to }: { agent: Agent; label: string; value: string; share: number; sub?: string; to?: string }) {
  return (
    <li className="grid grid-cols-[minmax(0,11rem)_1fr_auto] items-center gap-3 py-2 text-sm">
      <span className="min-w-0">
        <span className="flex items-center gap-1.5"><span className="inline-block h-2 w-2 flex-none rounded-sm" style={{ background: AGENT_COLORS[agent] }} aria-hidden="true" /><span className="sr-only">{AGENT_LABELS[agent]}: </span>{to ? <Link to={to} className="truncate font-medium text-ink hover:text-forest">{label}</Link> : <span className="truncate font-medium text-ink" title={label}>{label}</span>}</span>
        {sub && <span className="block truncate pl-3.5 text-xs text-ink-subtle">{sub}</span>}
      </span>
      <span className="h-2.5 overflow-hidden rounded-full bg-sage-pale" aria-hidden="true"><span className="block h-full rounded-full" style={{ width: `${Math.max(2, share * 100)}%`, background: AGENT_COLORS[agent] }} /></span>
      <span className="text-right tabular-nums text-ink">{value}</span>
    </li>
  );
}

/** What the agents spent their work on, for the whole range or the bucket chosen in the chart. */
export function UsageBreakdown({ report, caption, projects }: { report: UsageReport; caption: string; projects?: React.ReactNode }) {
  const [tab, setTab] = useState<Tab>("model");
  const id = useId();
  const models = report.by_model ?? [];
  const tools = report.by_tool ?? [];
  const sessions = report.sessions ?? [];
  const projectRows = [...(report.projects ?? []), ...(report.other_folders ?? [])];
  const topTokens = Math.max(1, ...models.map((m) => m.fresh_tokens));
  const topOutput = Math.max(1, ...tools.map((tool) => tool.output_chars || tool.calls));
  const topProject = Math.max(1, ...projectRows.map((p) => p.fresh_tokens));
  const topSession = Math.max(1, ...sessions.map((s) => s.fresh_tokens));
  const byTask = report.by_task;
  const taskRows = byTask?.tasks ?? [];
  const topTask = Math.max(1, ...taskRows.map((row) => row.fresh_tokens));
  const estimates = report.token_estimates;
  const estimateRows = estimates?.models ?? [];
  const topActual = Math.max(1, ...estimateRows.map((row) => row.actual_tokens));
  const percent = (n: number) => new Intl.NumberFormat(locale(), { style: "percent", maximumFractionDigits: 0 }).format(n);
  const factor = (n: number) => new Intl.NumberFormat(locale(), { maximumFractionDigits: 2 }).format(n);

  /** Arrow keys, Home and End move between tabs, as in any tab list. */
  function moveTab(e: React.KeyboardEvent<HTMLButtonElement>, current: Tab) {
    const index = TABS.findIndex((item) => item.value === current);
    const targets: Record<string, number> = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: TABS.length - 1 };
    const target = targets[e.key];
    if (target === undefined) return;
    e.preventDefault();
    const next = TABS[(target + TABS.length) % TABS.length].value;
    setTab(next);
    document.getElementById(`${id}-${next}`)?.focus();
  }

  return (
    <section aria-label={t("Usage breakdown")}>
      <div role="tablist" aria-label={t("Breakdown")} className="flex gap-1 border-b border-line">
        {TABS.map((item) => <button key={item.value} id={`${id}-${item.value}`} role="tab" type="button" aria-selected={tab === item.value} aria-controls={`${id}-panel`} tabIndex={tab === item.value ? 0 : -1} onClick={() => setTab(item.value)} onKeyDown={(e) => moveTab(e, item.value)} className={`section-tab ${tab === item.value ? "section-tab-active" : ""}`}>{item.label}</button>)}
      </div>
      <p className="mt-3 text-xs text-ink-subtle">{caption}</p>
      <div role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-${tab}`}>
      <ul className="mt-1 divide-y divide-line">
        {tab === "model" && (models.length ? models.map((m) => <Row key={m.agent + m.model} agent={m.agent} label={prettyModel(m.model)} sub={tp(m.replies, "{count} reply", "{count} replies")} value={formatTokens(m.fresh_tokens)} share={m.fresh_tokens / topTokens} />) : <Empty />)}
        {tab === "tool" && (tools.length ? tools.map((tool) => <Row key={tool.agent + tool.tool} agent={tool.agent} label={TOOL_NAMES[tool.tool] ?? tool.tool} sub={`${tool.tool}, ${tp(tool.calls, "{count} call", "{count} calls")}`} value={tool.output_chars ? chars(tool.output_chars) : tp(tool.calls, "{count} call", "{count} calls")} share={(tool.output_chars || tool.calls) / topOutput} />) : <Empty />)}
        {tab === "project" && projects ? <li className="py-1">{projects}</li> : tab === "project" && (projectRows.length ? projectRows.map((p) => <Row key={p.project_id ?? p.name} agent={report.agent ?? "claude"} label={p.name} sub={`${formatDuration(p.active_seconds)}, ${tp(p.sessions, "{count} session", "{count} sessions")}`} value={formatTokens(p.fresh_tokens)} share={p.fresh_tokens / topProject} to={p.project_id ? projectPath(p.project_id) : undefined} />) : <Empty />)}
        {tab === "task" && (taskRows.length ? taskRows.map((row) => <Row key={row.task_id} agent={report.agent ?? "claude"} label={`${row.task} ${row.title}`} sub={[row.status === "completed" ? t("Task completed") : t("Task not completed yet"), tp(row.replies, "{count} reply", "{count} replies")].join(", ")} value={formatTokens(row.fresh_tokens)} share={row.fresh_tokens / topTask} to={taskPath(row.project_id, row.task)} />) : <Empty />)}
        {tab === "estimate" && (estimateRows.length ? estimateRows.map((row) => <Row key={row.model} agent="claude" label={prettyModel(row.model)} sub={[tp(row.packs, "{count} pack measured", "{count} packs measured"), t("estimated {estimated}, real {actual}", { estimated: formatTokens(row.estimated_tokens), actual: formatTokens(row.actual_tokens) }), t("off by {fixed} with ×{factor}", { fixed: percent(row.error_fixed), factor: factor(estimates!.fixed_factor) }), row.error_measured != null ? t("{error} with its measured ×{factor}", { error: percent(row.error_measured), factor: factor(row.factor) }) : ""].filter(Boolean).join(", ")} value={`×${factor(row.factor)}`} share={row.actual_tokens / topActual} />) : <Empty />)}
        {tab === "session" && (sessions.length ? sessions.map((s) => <Row key={s.agent + s.session} agent={s.agent} label={s.project} sub={[formatDuration(s.active_seconds), tp(s.replies, "{count} reply", "{count} replies"), s.compactions ? t("compacted {count}×", { count: s.compactions }) : "", s.models.map(prettyModel).join(" + ")].filter(Boolean).join(", ")} value={formatTokens(s.fresh_tokens)} share={s.fresh_tokens / topSession} to={s.project_id ? projectPath(s.project_id) : undefined} />) : <Empty />)}
      </ul>
      </div>
      {tab === "task" && byTask && <p className="mt-2 text-xs text-ink-subtle">{byTask.fresh_tokens_per_completed_task != null ? t("{tokens} per completed task, from the agents' own logs.", { tokens: formatTokens(byTask.fresh_tokens_per_completed_task) }) + " " : ""}{t("A reply counts toward the task its own session last worked on, matched by the session's id; a session Project Moah has no record of counts toward the task last changed in that project.")}{byTask.unassigned_fresh_tokens ? " " + (byTask.unassigned_share != null ? t("{tokens} ({share}) matched no task.", { tokens: formatTokens(byTask.unassigned_fresh_tokens), share: percent(byTask.unassigned_share) }) : t("{tokens} matched no task.", { tokens: formatTokens(byTask.unassigned_fresh_tokens) })) : ""}</p>}
      {tab === "estimate" && estimates && <p className="mt-2 text-xs text-ink-subtle">{t("Claude's tokenizer is not public, so Project Moah estimates Claude tokens and checks each context pack against how much it really added, read from Claude Code's own logs on this computer.")} {estimates.in_use ? t("Packs are now sized with ×{factor}, measured on {model}.", { factor: factor(estimates.in_use.factor), model: prettyModel(estimates.in_use.model) }) : t("The measured factor is used once {count} packs of one model were measured; until then ×{factor}.", { count: estimates.min_packs, factor: factor(estimates.fixed_factor) })}</p>}
      {tab === "tool" && <p className="mt-2 text-xs text-ink-subtle">{t("Bars show how much output each tool fed back to the agent, which it then rereads. Only sizes are counted, never the text.")}</p>}
    </section>
  );
}

function Empty() { return <li className="py-3 text-sm text-ink-muted">{t("Nothing in this range.")}</li>; }

import { useQuery } from "@tanstack/react-query";
import { Check, Copy } from "lucide-react";
import { useEffect, useState } from "react";
import { contextSeenKey } from "../onboarding/GettingStarted";
import { writePref } from "../../lib/prefs";
import { contextApi } from "../../api/context";
import { memoryApi } from "../../api/memory";
import { HandoffButton } from "../handoff/HandoffButton";
import { Button, ErrorState, HelpTip } from "../ui";
import { useTasks } from "../../hooks/useTasks";
import type { DetailLevel } from "../../types/context";
import { useTimeout } from "../../hooks/useTimeout";
import { labels, msg, t, tx } from "../../lib/i18n";

const levels: { value: DetailLevel; label: string; hint: string }[] = [
  labels({ value: "minimal", label: msg("Minimal"), hint: msg("Task, unfinished requirements, next action, key decisions, latest checkpoint.") }, ["label", "hint"]),
  labels({ value: "balanced", label: msg("Balanced"), hint: msg("Adds rules, known issues, dependencies, and recent activity.") }, ["label", "hint"]),
  labels({ value: "detailed", label: msg("Detailed"), hint: msg("Adds more decisions, earlier checkpoints, and replaced decisions.") }, ["label", "hint"]),
];
const budgets = [labels({ label: msg("Default for this level"), value: 0 }, ["label"]), labels({ label: msg("About 750"), value: 750 }, ["label"]), labels({ label: msg("About 1,500"), value: 1500 }, ["label"]), labels({ label: msg("About 3,000"), value: 3000 }, ["label"])];
/** The pack's section names, keyed as the backend names them; the pack text itself stays in English for agents. */
const sectionLabels: Record<string, string> = labels({
  project: msg("Project"), shelves: msg("Active shelves"), global: msg("Global rules"), milestone: msg("Milestone"), task: msg("Current task"),
  status: msg("Status"), goal: msg("Goal"), criteria: msg("Acceptance criteria"), next: msg("Next action"), blockers: msg("Blockers"),
  decisions: msg("Important decisions"), rules: msg("Project rules"), warnings: msg("Warnings"), issues: msg("Known issues"), facts: msg("Facts"),
  routed: msg("From the global brain"), files: msg("Relevant files"), checkpoint: msg("Latest checkpoint"), dependencies: msg("Dependencies"),
  related: msg("Related tasks"), ideas: msg("Ideas"), notes: msg("Notes"), history: msg("Earlier checkpoints"), superseded: msg("Replaced decisions"),
  activity: msg("Recent activity"),
});

/** The backend's notes about which task the pack was built for. */
function packNote(text: string): string {
  const focus = /^No task was given, so the current focus (\S+) was used\.$/.exec(text);
  if (focus) return t("No task was given, so the current focus {id} was used.", { id: focus[1] });
  if (text === "No task was given and no current focus is set; this is a project overview.") return t("No task was given and no current focus is set; this is a project overview.");
  return text;
}

const omittedLabels: Record<string, string> = labels({ hidden: msg("hidden from AI"), "manual only": msg("manual only, not selected"), "not related": msg("not related to this task"), "detail level": msg("left out at this detail level"), budget: msg("left out to stay within the size"), "excluded by you": msg("excluded by you") });

export function ContextInspector({ projectId, focusTaskId }: { projectId: string; focusTaskId: string | null }) {
  const tasks = useTasks(projectId);
  const [task, setTask] = useState<string>("");
  const [detail, setDetail] = useState<DetailLevel>("balanced");
  const [budget, setBudget] = useState(0);
  const [include, setInclude] = useState<string[]>([]);
  const [copied, setCopied] = useState(false);
  const [showText, setShowText] = useState(false);
  const later = useTimeout();
  const manual = useQuery({ queryKey: ["memory-manual", projectId], queryFn: ({ signal }) => memoryApi.list(projectId, { visibility: ["manual_only"], statuses: ["active"] }, signal) });
  const pack = useQuery({
    queryKey: ["context", projectId, task, detail, budget, include],
    queryFn: ({ signal }) => contextApi.pack(projectId, { task: task || null, detail, budget: budget || null, include }, signal),
    placeholderData: (previous) => previous,
  });
  const openTasks = (tasks.data ?? []).filter((t) => t.status !== "completed" && t.status !== "archived");
  const focusRef = openTasks.find((t) => t.id === focusTaskId)?.human_id;
  const data = pack.data;
  useEffect(() => { if (pack.isSuccess) writePref(contextSeenKey(projectId), "1"); }, [pack.isSuccess, projectId]);
  const maxTokens = Math.max(1, ...(data?.sections.map((s) => s.tokens) ?? [1]));

  async function copy() {
    if (!data) return;
    try { await navigator.clipboard.writeText(data.text); setCopied(true); later(() => setCopied(false), 2000); } catch { setShowText(true); }
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
      <section aria-labelledby="ctx-settings" className="space-y-5 rounded-xl border border-line bg-surface p-6 shadow-card">
        <div>
          <h2 id="ctx-settings" className="text-base font-semibold tracking-tight">{t("AI context")} <HelpTip label={t("how AI context works")}>{t("Project Moah does not send your whole project history to an agent. It builds a small Context Pack from what relates to the current task. This is a preview of that pack.")}</HelpTip></h2>
          <p className="mt-1 text-sm text-ink-muted">{t("Preview what an agent would receive for a task.")}</p>
        </div>
        <div>
          <label htmlFor="ctx-task" className="field-label">{t("Task")}</label>
          <select id="ctx-task" className="field-input" value={task} onChange={(e) => setTask(e.target.value)}>
            <option value="">{focusRef ? `Current focus (${focusRef})` : t("No task (project overview)")}</option>
            {openTasks.map((t) => <option key={t.id} value={t.human_id}>{t.human_id} {t.title}</option>)}
          </select>
        </div>
        <fieldset>
          <legend className="field-label">{t("Detail")}</legend>
          <div className="space-y-2">
            {levels.map((l) => (
              <label key={l.value} className={`flex cursor-pointer gap-3 rounded-xl border p-3 text-sm ${detail === l.value ? "border-forest bg-sage-pale" : "border-line"}`}>
                <input type="radio" name="ctx-detail" value={l.value} checked={detail === l.value} onChange={() => setDetail(l.value)} className="mt-1 accent-primary" />
                <span><strong className="block text-ink">{l.label}</strong><span className="text-xs text-ink-muted">{l.hint}</span></span>
              </label>
            ))}
          </div>
        </fieldset>
        <div>
          <label htmlFor="ctx-budget" className="field-label">{t("Size limit")} <HelpTip label={t("size limit")}>{t("A rough cap on the pack's length. When it is tight, the least important items go first. Essential task details always stay.")}</HelpTip></label>
          <select id="ctx-budget" className="field-input" value={budget} onChange={(e) => setBudget(Number(e.target.value))}>{budgets.map((b) => <option key={b.value} value={b.value}>{b.label}</option>)}</select>
        </div>
        {manual.data && manual.data.length > 0 && (
          <fieldset>
            <legend className="field-label">{t("Include manual-only memory")} <HelpTip label={t("manual-only memory")}>{t("Manual-only memory is never sent unless you choose it here.")}</HelpTip></legend>
            <div className="space-y-1.5">{manual.data.map((m) => <label key={m.id} className="flex items-start gap-2 text-sm"><input type="checkbox" checked={include.includes(m.human_id)} onChange={(e) => setInclude(e.target.checked ? [...include, m.human_id] : include.filter((r) => r !== m.human_id))} className="mt-1 h-4 w-4 accent-primary" /><span><strong>{m.human_id}</strong> {m.title}</span></label>)}</div>
          </fieldset>
        )}
      </section>

      <section aria-labelledby="ctx-result" aria-live="polite" className="min-w-0 space-y-5">
        {pack.isError && !data ? <ErrorState title={t("Context could not be built")} message={pack.error.message} onRetry={() => void pack.refetch()} />
          : !data ? <div role="status" aria-label={t("Building context")} className="h-64 animate-pulse rounded-xl bg-surface" />
          : <>
            <div className="rounded-xl border border-line bg-surface p-6 shadow-card">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h2 id="ctx-result" className="text-base font-semibold tracking-tight">{data.task ? t("Context for {task}", { task: data.task }) : t("Project overview")}</h2>
                  <p className="mt-1 text-sm text-ink-muted">{tx("Estimated size <b>about {size} tokens</b>, limit about {limit}. Estimates are approximate.", { b: (text) => <strong className="text-ink">{text}</strong>, size: data.estimated_tokens, limit: data.budget })}</p>
                </div>
                <div className="flex gap-2">
                  <Button onClick={() => setShowText((v) => !v)} aria-expanded={showText}>{showText ? t("Hide text") : t("Preview context")}</Button>
                  <Button variant="primary" onClick={() => void copy()}>{copied ? <Check size={16} /> : <Copy size={16} />}{copied ? t("Copied") : t("Copy")}</Button>
                </div>
              </div>
              {data.over_budget && <p role="status" className="mt-3 rounded-xl bg-warning-soft px-3 py-2 text-sm text-warning-ink">{t("The essential task details alone are larger than the limit, so they were kept anyway.")}</p>}
              {data.warnings.map((w) => <p key={w} className="mt-3 rounded-xl bg-sage-pale px-3 py-2 text-sm text-ink">{packNote(w)}</p>)}
              <h3 className="mt-6 text-sm font-semibold text-ink">{t("Included")}</h3>
              <ul className="mt-2 space-y-1.5">
                {data.sections.map((s) => (
                  <li key={s.key} className="grid grid-cols-[minmax(0,9rem)_1fr_4rem] items-center gap-3 text-sm">
                    <span className="truncate text-ink-muted" title={sectionLabels[s.key] ?? s.title}>{sectionLabels[s.key] ?? s.title}</span>
                    <span className="h-2 overflow-hidden rounded-full bg-neutral-soft" aria-hidden="true"><span className="block h-full rounded-full bg-primary" style={{ width: `${Math.max(4, (s.tokens / maxTokens) * 100)}%` }} /></span>
                    <span className="text-right text-xs font-medium text-ink-muted">~{s.tokens}</span>
                  </li>
                ))}
              </ul>
              {Object.keys(data.omitted).length > 0 && (
                <div className="mt-5 border-t border-line pt-4">
                  <h3 className="text-sm font-semibold text-ink">{t("Left out")}</h3>
                  <ul className="mt-1.5 space-y-0.5 text-sm text-ink-muted">{Object.entries(data.omitted).map(([why, count]) => <li key={why}>{count} {omittedLabels[why] ?? why}</li>)}</ul>
                </div>
              )}
            </div>
            <div className="rounded-xl border border-line bg-surface p-6 shadow-card"><h3 className="text-sm font-semibold text-ink">{t("Hand off to another agent")}</h3><p className="mt-1 text-sm text-ink-muted">{t("A short note covering what is done, what remains, and what to do next. It works with any coding agent.")}</p><div className="mt-3"><HandoffButton projectId={projectId} task={task || data.task} /></div></div>
            {showText && <pre aria-label={t("Context preview")} className="max-h-[32rem] overflow-auto whitespace-pre-wrap rounded-xl border border-line bg-surface p-6 text-xs leading-6 text-ink shadow-card">{data.text}</pre>}
          </>}
      </section>
    </div>
  );
}

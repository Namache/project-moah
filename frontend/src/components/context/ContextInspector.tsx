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

const levels: { value: DetailLevel; label: string; hint: string }[] = [
  { value: "minimal", label: "Minimal", hint: "Task, unfinished requirements, next action, key decisions, latest checkpoint." },
  { value: "balanced", label: "Balanced", hint: "Adds rules, known issues, dependencies, and recent activity." },
  { value: "detailed", label: "Detailed", hint: "Adds more decisions, earlier checkpoints, and replaced decisions." },
];
const budgets = [{ label: "Default for this level", value: 0 }, { label: "About 750", value: 750 }, { label: "About 1,500", value: 1500 }, { label: "About 3,000", value: 3000 }];
const omittedLabels: Record<string, string> = { hidden: "hidden from AI", "manual only": "manual only, not selected", "not related": "not related to this task", "detail level": "left out at this detail level", budget: "left out to stay within the size", "excluded by you": "excluded by you" };

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
          <h2 id="ctx-settings" className="text-base font-semibold tracking-tight">AI context <HelpTip label="how AI context works">Project Moah does not send your whole project history to an agent. It builds a small Context Pack from what relates to the current task. This is a preview of that pack.</HelpTip></h2>
          <p className="mt-1 text-sm text-ink-muted">Preview what an agent would receive for a task.</p>
        </div>
        <div>
          <label htmlFor="ctx-task" className="field-label">Task</label>
          <select id="ctx-task" className="field-input" value={task} onChange={(e) => setTask(e.target.value)}>
            <option value="">{focusRef ? `Current focus (${focusRef})` : "No task (project overview)"}</option>
            {openTasks.map((t) => <option key={t.id} value={t.human_id}>{t.human_id} {t.title}</option>)}
          </select>
        </div>
        <fieldset>
          <legend className="field-label">Detail</legend>
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
          <label htmlFor="ctx-budget" className="field-label">Size limit <HelpTip label="size limit">A rough cap on the pack's length. When it is tight, the least important items go first. Essential task details always stay.</HelpTip></label>
          <select id="ctx-budget" className="field-input" value={budget} onChange={(e) => setBudget(Number(e.target.value))}>{budgets.map((b) => <option key={b.value} value={b.value}>{b.label}</option>)}</select>
        </div>
        {manual.data && manual.data.length > 0 && (
          <fieldset>
            <legend className="field-label">Include manual-only memory <HelpTip label="manual-only memory">Manual-only memory is never sent unless you choose it here.</HelpTip></legend>
            <div className="space-y-1.5">{manual.data.map((m) => <label key={m.id} className="flex items-start gap-2 text-sm"><input type="checkbox" checked={include.includes(m.human_id)} onChange={(e) => setInclude(e.target.checked ? [...include, m.human_id] : include.filter((r) => r !== m.human_id))} className="mt-1 h-4 w-4 accent-primary" /><span><strong>{m.human_id}</strong> {m.title}</span></label>)}</div>
          </fieldset>
        )}
      </section>

      <section aria-labelledby="ctx-result" aria-live="polite" className="min-w-0 space-y-5">
        {pack.isError && !data ? <ErrorState title="Context could not be built" message={pack.error.message} onRetry={() => void pack.refetch()} />
          : !data ? <div role="status" aria-label="Building context" className="h-64 animate-pulse rounded-xl bg-surface" />
          : <>
            <div className="rounded-xl border border-line bg-surface p-6 shadow-card">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h2 id="ctx-result" className="text-base font-semibold tracking-tight">{data.task ? `Context for ${data.task}` : "Project overview"}</h2>
                  <p className="mt-1 text-sm text-ink-muted">Estimated size <strong className="text-ink">about {data.estimated_tokens.toLocaleString()} tokens</strong>, limit about {data.budget.toLocaleString()}. Estimates are approximate.</p>
                </div>
                <div className="flex gap-2">
                  <Button onClick={() => setShowText((v) => !v)} aria-expanded={showText}>{showText ? "Hide text" : "Preview context"}</Button>
                  <Button variant="primary" onClick={() => void copy()}>{copied ? <Check size={16} /> : <Copy size={16} />}{copied ? "Copied" : "Copy"}</Button>
                </div>
              </div>
              {data.over_budget && <p role="status" className="mt-3 rounded-xl bg-warning-soft px-3 py-2 text-sm text-warning-ink">The essential task details alone are larger than the limit, so they were kept anyway.</p>}
              {data.warnings.map((w) => <p key={w} className="mt-3 rounded-xl bg-sage-pale px-3 py-2 text-sm text-ink">{w}</p>)}
              <h3 className="mt-6 text-sm font-semibold text-ink">Included</h3>
              <ul className="mt-2 space-y-1.5">
                {data.sections.map((s) => (
                  <li key={s.key} className="grid grid-cols-[minmax(0,9rem)_1fr_4rem] items-center gap-3 text-sm">
                    <span className="truncate text-ink-muted" title={s.title}>{s.title}</span>
                    <span className="h-2 overflow-hidden rounded-full bg-neutral-soft" aria-hidden="true"><span className="block h-full rounded-full bg-primary" style={{ width: `${Math.max(4, (s.tokens / maxTokens) * 100)}%` }} /></span>
                    <span className="text-right text-xs font-medium text-ink-muted">~{s.tokens}</span>
                  </li>
                ))}
              </ul>
              {Object.keys(data.omitted).length > 0 && (
                <div className="mt-5 border-t border-line pt-4">
                  <h3 className="text-sm font-semibold text-ink">Left out</h3>
                  <ul className="mt-1.5 space-y-0.5 text-sm text-ink-muted">{Object.entries(data.omitted).map(([why, count]) => <li key={why}>{count} {omittedLabels[why] ?? why}</li>)}</ul>
                </div>
              )}
            </div>
            <div className="rounded-xl border border-line bg-surface p-6 shadow-card"><h3 className="text-sm font-semibold text-ink">Hand off to another agent</h3><p className="mt-1 text-sm text-ink-muted">A short note covering what is done, what remains, and what to do next. It works with any coding agent.</p><div className="mt-3"><HandoffButton projectId={projectId} task={task || data.task} /></div></div>
            {showText && <pre aria-label="Context preview" className="max-h-[32rem] overflow-auto whitespace-pre-wrap rounded-xl border border-line bg-surface p-6 text-xs leading-6 text-ink shadow-card">{data.text}</pre>}
          </>}
      </section>
    </div>
  );
}

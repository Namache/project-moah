import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Camera, Check, CircleCheck, CircleHelp, CircleX, Layers, NotebookText, SquareArrowOutUpRight } from "lucide-react";
import { reviewsApi } from "../../api/reviews";
import { useTaskReview } from "../../hooks/useReviews";
import { notify } from "../../lib/notify";
import { t, tp } from "../../lib/i18n";
import type { ReviewItem } from "../../types/review";
import { Button } from "../ui";
import { TYPING, useSingleKeys } from "../../lib/reviewKeys";
import { agentName } from "./reviewBits";

/** One task of the batch: its own lines, picked out of the notes, and a way to open it alone. */
/** Why a task should not go to Done with the rest by default, or null when nothing says so. */
export function unfinished(notDone: number, openCriteria: number): string | null {
  if (notDone > 0) return tp(notDone, "{count} not done", "{count} not done");
  if (openCriteria > 0) return tp(openCriteria, "{count} criterion not ticked", "{count} criteria not ticked");
  return null;
}

function Member({ item, included, onInclude, onOpen, onRead }: { item: ReviewItem; included: boolean; onInclude: (on: boolean) => void; onOpen: () => void; onRead: (reason: string | null) => void }) {
  const review = useTaskReview(item.project_id, item.ref);
  const round = review.data?.current;
  const criteria = review.data?.criteria.length ?? 0;
  const open = review.data?.criteria.filter((criterion) => !criterion.is_completed).length ?? 0;
  const reason = round ? unfinished(round.not_done.length, open) : null;
  const read = useRef(onRead);
  read.current = onRead;
  useEffect(() => {
    if (review.data) read.current(reason);
  }, [review.data, reason]);
  return (
    <li className={`rounded-xl border bg-surface p-4 transition-opacity ${included ? "border-line" : "border-dashed border-line opacity-60"}`}>
      <div className="flex items-start gap-3">
        <input type="checkbox" checked={included} onChange={(event) => onInclude(event.target.checked)} aria-label={t("Accept {task} with the batch", { task: item.ref })}
          className="mt-1 h-4 w-4 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <h3 className="text-base font-semibold text-ink">{item.title}</h3>
            <span className="text-xs font-medium text-ink-subtle">{item.ref}</span>
            {item.generated && <span className="inline-flex items-center gap-0.5 rounded bg-neutral-soft px-1 text-xs font-semibold text-neutral-ink"><NotebookText size={11} aria-hidden="true" />{t("No report")}</span>}
            {item.screenshots > 0 && <span className="inline-flex items-center gap-0.5 text-xs text-ink-subtle"><Camera size={12} aria-hidden="true" />{tp(item.screenshots, "{count} screenshot", "{count} screenshots")}</span>}
            {criteria > 0 && <span className="text-xs text-ink-subtle">{tp(criteria, "{count} criterion to check", "{count} criteria to check")}</span>}
            {reason && !included && <span className="rounded bg-warning-soft px-1 text-xs font-semibold text-warning-ink">{t("Left unticked: {reason}", { reason })}</span>}
            <button type="button" onClick={onOpen} className="ml-auto inline-flex items-center gap-1 text-xs font-semibold text-forest hover:underline focus-visible:outline-2 focus-visible:outline-forest">
              {t("Open on its own")}<SquareArrowOutUpRight size={12} aria-hidden="true" />
            </button>
          </div>
          {review.isPending ? <div className="mt-2 h-10 animate-pulse rounded-lg bg-neutral-soft" />
            : !round ? null
            : (
              <ul className="mt-2 space-y-1 text-sm leading-6">
                {round.summary && !round.generated && <li className="text-ink-muted">{round.summary}</li>}
                {round.done.map((line, i) => <li key={`d${i}`} className="flex gap-2"><CircleCheck size={16} className="mt-1 shrink-0 text-success" aria-hidden="true" /><span>{line}</span></li>)}
                {round.not_done.map((line, i) => <li key={`n${i}`} className="flex gap-2"><CircleX size={16} className="mt-1 shrink-0 text-danger" aria-hidden="true" /><span>{line}</span></li>)}
                {round.done.length + round.not_done.length === 0 && <li className="flex gap-2 text-ink-muted"><CircleHelp size={16} className="mt-1 shrink-0" aria-hidden="true" />{t("Its notes say nothing about this task on its own. Open it to check.")}</li>}
                {round.generated && round.done.length > 0 && round.not_done.length === 0 && <li className="flex gap-2 text-xs text-ink-subtle"><CircleHelp size={14} className="mt-0.5 shrink-0" aria-hidden="true" />{t("Its notes don't say what is left.")}</li>}
              </ul>
            )}
        </div>
      </div>
    </li>
  );
}

/**
 * The tasks one agent note covered, on one page: each with its own lines. Accept the ones you
 * keep ticked in one go, or open one on its own to send it back. Key A accepts the batch.
 */
export function BatchPanel({ batch, items, onOpen, onDone }: { batch: string; items: ReviewItem[]; onOpen: (item: ReviewItem) => void; onDone: (accepted: ReviewItem[]) => void }) {
  // What you ticked or unticked yourself; until then a task is ticked unless its lines say
  // it isn't finished (something not done, a criterion not ticked).
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [reasons, setReasons] = useState<Record<string, string | null>>({});
  const included = (item: ReviewItem) => picked[item.key] ?? !reasons[item.key];
  const ready = items.every((item) => item.key in reasons);
  const [busy, setBusy] = useState(false);
  const client = useQueryClient();
  const title = items[0]?.batch_title || t("One agent note");
  const chosen = items.filter(included);
  const agents = [...new Set(items.map((item) => agentName(item.agent)))].join(", ");

  async function undo(accepted: ReviewItem[]) {
    const failed: string[] = [];
    for (const item of accepted) {
      try { await reviewsApi.undo(item.project_id, item.ref); } catch { failed.push(item.ref); }
    }
    await client.invalidateQueries();
    notify(failed.length ? t("Could not undo {tasks}.", { tasks: failed.join(", ") }) : tp(accepted.length, "Undone. {count} task waits in Review again.", "Undone. {count} tasks wait in Review again."), failed.length ? "danger" : "success", { group: "review-decision" });
  }

  async function acceptAll() {
    if (!chosen.length || busy || !ready) return;
    setBusy(true);
    const accepted: ReviewItem[] = [];
    const failed: string[] = [];
    for (const item of chosen) {
      try {
        await reviewsApi.decide(item.project_id, item.ref, { verdict: "accept", comment: "", criteria: [] });
        accepted.push(item);
      } catch {
        failed.push(item.ref);
      }
    }
    await client.invalidateQueries();
    setBusy(false);
    if (accepted.length) {
      notify(tp(accepted.length, "Accepted {count} task. It is in Done.", "Accepted {count} tasks. They are in Done."), "success", { group: "review-decision", action: { label: t("Undo"), run: () => undo(accepted) } });
    }
    if (failed.length) notify(t("Could not accept {tasks}. Open them on their own.", { tasks: failed.join(", ") }), "danger");
    onDone(accepted);
  }

  const singleKeys = useSingleKeys();
  const keys = useRef({ acceptAll, singleKeys });
  keys.current = { acceptAll, singleKeys };
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (!keys.current.singleKeys || event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || event.repeat) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest(TYPING)) return;
      if (event.key.toLowerCase() === "a") { event.preventDefault(); void keys.current.acceptAll(); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <>
      <div className="relative min-h-0 flex-1 overflow-y-auto px-5 py-6 sm:px-8">
        <div className="mx-auto max-w-5xl">
          <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-ink-subtle"><Layers size={14} aria-hidden="true" />{t("Batch from one agent note")}</p>
          <h2 id="review-title" className="mt-1.5 text-2xl font-semibold leading-tight tracking-tight text-ink">{title}</h2>
          <p className="mt-2 text-sm text-ink-muted">{tp(items.length, "{count} task {agent} finished together. Untick any you don't want to accept yet; open one on its own to send it back.", "{count} tasks {agent} finished together. Untick any you don't want to accept yet; open one on its own to send it back.", { agent: agents })}</p>
          <ul className="mt-4 space-y-3" aria-label={t("Tasks in this batch")}>
            {items.map((item) => <Member key={item.key} item={item} included={included(item)} onInclude={(on) => setPicked((now) => ({ ...now, [item.key]: on }))} onOpen={() => onOpen(item)}
              onRead={(reason) => setReasons((now) => (now[item.key] === reason && item.key in now ? now : { ...now, [item.key]: reason }))} />)}
          </ul>
        </div>
      </div>
      <div data-keep-clear="" className="flex flex-wrap items-center gap-3 border-t border-line bg-surface px-5 py-3" data-batch={batch}>
        <p className="min-w-0 flex-1 text-xs text-ink-subtle">{t("Accepting here leaves acceptance criteria unticked. To tick them, open the task on its own.")}</p>
        <Button variant="primary" disabled={busy || !ready || !chosen.length} onClick={() => void acceptAll()} aria-keyshortcuts={singleKeys ? "A" : undefined}>
          <Check size={16} aria-hidden="true" />{busy ? t("Accepting…") : tp(chosen.length, "Accept {count} and move to Done", "Accept {count} and move to Done")}
        </Button>
      </div>
    </>
  );
}

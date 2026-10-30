import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { ArrowLeft, Check, ChevronDown, PartyPopper, Undo2, X } from "lucide-react";
import { useMemoryActions, useMemoryList } from "../../hooks/useMemory";
import type { MemoryRecord } from "../../types/memory";
import { Button, formatDate } from "../ui";
import { useModalDialog } from "../../hooks/useModalDialog";
import { t } from "../../lib/i18n";

type Decision = "resolved" | "pending" | "skipped";
interface Step { memory: MemoryRecord; decision: Decision; previousNote: string | null; noteChanged: boolean }

const SWIPE_DISTANCE = 120;
const issueFilters = { types: ["bug" as const], statuses: ["active" as const], resolved: false, sort: "priority" as const, limit: 500 };

export function IssueReview({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const dialogRef = useModalDialog();
  const drag = useRef<{ x: number; id: number } | null>(null);
  const list = useMemoryList(projectId, issueFilters, true, true);
  const actions = useMemoryActions(projectId);
  // The queue is fixed from the first list fetched for this review, never from older cached data,
  // so cards do not shift while you review and issues resolved elsewhere do not come back.
  const [queue, setQueue] = useState<MemoryRecord[] | null>(null);
  const [position, setPosition] = useState(0);
  const [steps, setSteps] = useState<Step[]>([]);
  const [note, setNote] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const current = queue?.[position];

  useEffect(() => { if (list.data && list.isFetchedAfterMount && !list.isFetching && queue === null) setQueue(list.data); }, [list.data, list.isFetchedAfterMount, list.isFetching, queue]);
  useEffect(() => { setNote(current?.pending_note ?? ""); setOffset(0); setError(""); }, [current?.id]);

  async function decide(decision: Decision) {
    if (!current || busy) return;
    const trimmed = note.trim();
    const noteChanged = decision === "pending" && trimmed !== (current.pending_note ?? "");
    setBusy(true);
    setError("");
    try {
      if (decision === "resolved") await actions.update.mutateAsync({ ref: current.id, changes: { is_resolved: true } });
      else if (noteChanged) await actions.update.mutateAsync({ ref: current.id, changes: { pending_note: trimmed || null } });
      setSteps((all) => [...all, { memory: current, decision, previousNote: current.pending_note, noteChanged }]);
      setPosition((value) => value + 1);
    } catch (cause) {
      setOffset(0);
      setError(cause instanceof Error ? cause.message : t("That change could not be saved."));
    } finally { setBusy(false); }
  }

  async function undo() {
    const last = steps[steps.length - 1];
    if (!last || busy) return;
    setBusy(true);
    setError("");
    try {
      if (last.decision === "resolved") await actions.update.mutateAsync({ ref: last.memory.id, changes: { is_resolved: false } });
      else if (last.noteChanged) await actions.update.mutateAsync({ ref: last.memory.id, changes: { pending_note: last.previousNote } });
      setSteps((all) => all.slice(0, -1));
      setPosition((value) => value - 1);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("That change could not be undone."));
    } finally { setBusy(false); }
  }

  function onKeyDown(event: KeyboardEvent) {
    const target = event.target as HTMLElement;
    if (target.tagName === "TEXTAREA" || target.tagName === "INPUT" || event.metaKey || event.ctrlKey || event.altKey) return;
    if (event.key === "ArrowRight") { event.preventDefault(); void decide("resolved"); }
    else if (event.key === "ArrowLeft") { event.preventDefault(); void decide("pending"); }
    else if (event.key === "ArrowDown") { event.preventDefault(); void decide("skipped"); }
  }

  function pointerDown(event: PointerEvent<HTMLDivElement>) {
    if ((event.target as HTMLElement).closest("textarea, button, a")) return;
    drag.current = { x: event.clientX, id: event.pointerId };
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function pointerMove(event: PointerEvent<HTMLDivElement>) {
    if (drag.current?.id === event.pointerId) setOffset(event.clientX - drag.current.x);
  }
  function pointerUp(event: PointerEvent<HTMLDivElement>) {
    if (drag.current?.id !== event.pointerId) return;
    const distance = event.clientX - drag.current.x;
    drag.current = null;
    if (distance > SWIPE_DISTANCE) void decide("resolved");
    else if (distance < -SWIPE_DISTANCE) void decide("pending");
    else setOffset(0);
  }

  const total = queue?.length ?? 0;
  const resolvedCount = steps.filter((step) => step.decision === "resolved").length;
  const pendingCount = steps.filter((step) => step.decision === "pending").length;
  const skippedCount = steps.filter((step) => step.decision === "skipped").length;
  const finished = queue !== null && position >= total;
  const leaning = offset > 40 ? "resolved" : offset < -40 ? "pending" : null;

  return (
    <dialog ref={dialogRef} aria-labelledby="issue-review-title" onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }} onKeyDown={onKeyDown}
      className="dialog-panel fixed inset-0 m-auto max-h-[92vh] w-[min(640px,calc(100vw-24px))] overflow-y-auto rounded-xl border border-line bg-surface p-0 text-ink shadow-dialog backdrop:bg-black/40">
      <div className="flex items-center justify-between gap-3 border-b border-line px-6 py-4">
        <div>
          <h2 id="issue-review-title" className="text-base font-semibold tracking-tight">{t("Check pending issues")}</h2>
          <p className="text-xs text-ink-muted" aria-live="polite">{queue === null ? t("Loading…") : finished ? t("All done") : t("{position} of {count}", { position: position + 1, count: total })}</p>
        </div>
        <Button variant="quiet" size="icon" onClick={onClose} aria-label={t("Close review")}><X size={18} /></Button>
      </div>

      <div className="px-6 py-5">
        {list.isError && <p role="alert" className="rounded-xl border border-danger/40 bg-danger-soft p-3 text-sm text-danger-ink">{list.error.message} <button type="button" className="font-semibold underline" onClick={() => void list.refetch()}>{t("Try again")}</button></p>}
        {queue === null && !list.isError && <p role="status" className="py-10 text-center text-sm text-ink-muted">{t("Loading pending issues…")}</p>}
        {queue !== null && total === 0 && <p className="py-10 text-center text-sm text-ink-muted">{t("There are no pending issues to review.")}</p>}

        {finished && total > 0 && (
          <div className="py-8 text-center">
            <PartyPopper size={34} className="mx-auto text-forest" aria-hidden="true" />
            <p className="mt-3 text-lg font-semibold">{t("Reviewed {count}", { count: total })}</p>
            <p className="mt-1 text-sm text-ink-muted">{t("{resolved} resolved, {pending} still pending", { resolved: resolvedCount, pending: pendingCount })}{skippedCount > 0 ? `, ${t("{count} skipped", { count: skippedCount })}` : ""}</p>
          </div>
        )}

        {current && (
          <div>
            <div role="group" aria-label={`${current.human_id}: ${current.title}`} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={() => { drag.current = null; setOffset(0); }}
              style={{ transform: `translateX(${offset}px) rotate(${offset / 25}deg)`, transition: drag.current ? "none" : "transform 0.2s" }}
              className={`relative cursor-grab touch-pan-y select-none rounded-xl border-2 p-5 ${leaning === "resolved" ? "border-success bg-success-soft" : leaning === "pending" ? "border-warning bg-warning-soft" : "border-danger/40 bg-danger-soft/60"}`}>
              {leaning && <span className={`absolute right-4 top-4 rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wide ${leaning === "resolved" ? "bg-success text-white" : "bg-warning text-white"}`}>{leaning === "resolved" ? t("Resolved") : t("Still pending")}</span>}
              <div className="flex items-center gap-2 text-xs font-semibold text-ink-muted"><span>{current.human_id}</span>{(current.importance === "high" || current.importance === "critical") && <span className="rounded-full bg-surface/80 px-2 py-0.5 capitalize text-ink">{current.importance}</span>}<span className="ml-auto font-normal">{t("Updated {date}", { date: formatDate(current.updated_at) })}</span></div>
              <h3 className="mt-3 text-xl font-semibold leading-snug">{current.title}</h3>
              {current.content && <p className="mt-3 max-h-56 overflow-y-auto whitespace-pre-line text-sm leading-6 text-ink-muted">{current.content}</p>}
              {(current.tasks.length > 0 || current.tags.length > 0) && <div className="mt-4 flex flex-wrap gap-1.5 text-xs">
                {current.tasks.map((task) => <span key={task.id} className="rounded-md bg-surface/80 px-2 py-1 font-medium">{t("Task {id}", { id: task.human_id })}: {task.title}</span>)}
                {current.tags.map((tag) => <span key={tag} className="rounded-md bg-surface/80 px-2 py-1 text-ink-muted">#{tag}</span>)}
              </div>}
            </div>

            <label htmlFor="issue-review-note" className="field-label mt-4 block">{t("Why is it still pending?")} <span className="font-normal text-ink-subtle">{t("(optional, saved with the issue)")}</span></label>
            <textarea id="issue-review-note" className="field-input" rows={2} maxLength={2000} value={note} onChange={(event) => setNote(event.target.value)} placeholder={t("Still crashes on old saves")} />

            {error && <p role="alert" className="mt-3 rounded-xl border border-danger/40 bg-danger-soft p-3 text-sm text-danger-ink">{error}</p>}

            <div className="mt-4 grid grid-cols-[1fr_auto_1fr] gap-2">
              <Button onClick={() => void decide("pending")} disabled={busy} className="!border-warning/40 !bg-warning-soft !text-warning-ink hover:!bg-warning-soft"><ArrowLeft size={16} aria-hidden="true" />{t("Still pending")}</Button>
              <Button variant="quiet" onClick={() => void decide("skipped")} disabled={busy}><ChevronDown size={16} aria-hidden="true" />{t("Skip")}</Button>
              <Button variant="primary" onClick={() => void decide("resolved")} disabled={busy}>{t("Resolved")}<Check size={16} aria-hidden="true" /></Button>
            </div>
            <p className="mt-3 text-center text-xs text-ink-subtle">{t("Drag the card or use the arrow keys: right resolves, left keeps it pending, down skips.")}</p>
          </div>
        )}

        <div className="mt-4 flex items-center justify-between gap-2">
          <Button variant="quiet" onClick={() => void undo()} disabled={busy || steps.length === 0}><Undo2 size={16} aria-hidden="true" />{t("Undo")}</Button>
          {finished && <Button variant="primary" onClick={onClose}>{t("Done")}</Button>}
        </div>
      </div>
    </dialog>
  );
}

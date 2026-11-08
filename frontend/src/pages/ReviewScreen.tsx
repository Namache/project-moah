import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { ClipboardCheck } from "lucide-react";
import { proposalsApi } from "../api/proposals";
import { AcceptAllButton } from "../components/proposals/AcceptAllButton";
import { ProposalCard } from "../components/proposals/ProposalCard";
import { PaneResizer, usePaneWidth } from "../components/PaneResizer";
import { ReopenBox, ReviewComposer, SendBackToAgent, type Quoted } from "../components/review/ReviewComposer";
import { ReviewDocument, type CriteriaTicks, type FollowUpActions } from "../components/review/ReviewDocument";
import { ReviewTimeline, useReviewFolds, type Folds } from "../components/review/ReviewTimeline";
import { EmptyState, ErrorState } from "../components/ui";
import { useFollowUps, useReviewTimeline, useTaskReview } from "../hooks/useReviews";
import { notify } from "../lib/notify";
import { queryKeys } from "../lib/queries";
import { t } from "../lib/i18n";
import type { ReviewDecisionInput, ReviewDetail, ReviewItem } from "../types/review";

function Loading({ label }: { label: string }) {
  return <div role="status" aria-label={label} className="space-y-3">{[0, 1, 2].map((i) => <div key={i} className="h-24 animate-pulse rounded-xl bg-neutral-soft" />)}</div>;
}

function SuggestionPanel({ item, waitingHere }: { item: ReviewItem; waitingHere: number }) {
  const proposal = useQuery({ queryKey: [...queryKeys.proposals(item.project_id), "one", item.ref], queryFn: ({ signal }) => proposalsApi.get(item.project_id, item.ref, signal) });
  if (proposal.isPending) return <Loading label={t("Loading the suggestion")} />;
  if (proposal.isError) return <ErrorState title={t("The suggestion could not be loaded")} message={proposal.error.message} onRetry={() => void proposal.refetch()} />;
  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-ink-muted">{t("{project}: an agent suggests a change that needs your decision. Nothing changes until you accept it.", { project: item.project_name })}</p>
        {waitingHere > 1 && <AcceptAllButton projectId={item.project_id} count={waitingHere} label={t("Accept all {count}", { count: waitingHere })} />}
      </div>
      <ul><ProposalCard proposal={proposal.data} readonly={false} /></ul>
    </div>
  );
}

function TaskPanel({ item, onDecided }: { item: ReviewItem; onDecided: (verdict: ReviewDecisionInput["verdict"], result: ReviewDetail) => void }) {
  const review = useTaskReview(item.project_id, item.ref);
  const [quote, setQuote] = useState<Quoted | null>(null);
  // Acceptance criteria start ticked while the work waits: you untick what isn't met.
  const [unticked, setUnticked] = useState<Record<string, boolean>>({});
  const [making, setMaking] = useState<string | null>(null);
  const followUps = useFollowUps(item.project_id, item.ref);
  if (review.isPending) return <div className="p-8"><Loading label={t("Loading the review")} /></div>;
  if (review.isError) return <div className="p-8"><ErrorState title={t("The review could not be loaded")} message={review.error.message} onRetry={() => void review.refetch()} /></div>;
  const detail = review.data;
  const round = detail.current;
  const waiting = round.status === "pending";
  const work = round.kind === "work";
  const project = { name: item.project_name, icon: item.project_icon, accent: item.project_accent };
  const put = (text: string, answer = false) => setQuote((q) => ({ text, n: (q?.n ?? 0) + 1, answer }));
  const ticks: CriteriaTicks | undefined = waiting && work ? { met: (id) => !unticked[id], set: (id, met) => setUnticked((u) => ({ ...u, [id]: !met })) } : undefined;
  // A line of an agent's own report can become a task, one at a time and only when you ask.
  const actions: FollowUpActions | undefined = work && !round.generated && (waiting || round.status === "accepted") ? {
    making,
    make: (text) => {
      setMaking(text);
      followUps.mutate({ items: [text] }, {
        onSuccess: (result) => { const made = result.current.follow_ups.find((f) => f.text === text); if (made) notify(t("Made {task} in To do.", { task: made.task_ref })); },
        onError: (cause) => notify(cause instanceof Error ? cause.message : t("The task could not be made."), "danger"),
        onSettled: () => setMaking(null),
      });
    },
  } : undefined;
  const handedBack = (round.status === "rejected" || round.status === "answered") && !round.moved_to && detail.task_status !== "review" && detail.task_status !== "blocked";
  const reopenable = work && round.status === "accepted" && (detail.task_status === "completed" || detail.task_status === "archived");
  return (
    <>
      <div className="relative min-h-0 flex-1 overflow-y-auto px-5 py-6 sm:px-8">
        <div className="mx-auto max-w-5xl">
          <ReviewDocument detail={detail} project={project} onQuote={(text) => put(text)} onPick={(text) => put(text, true)} ticks={ticks} followUps={actions} />
        </div>
      </div>
      {waiting
        ? <ReviewComposer detail={detail} quote={quote} criteria={detail.criteria.map((c) => ({ id: c.id, met: !unticked[c.id] }))} onDecided={onDecided} />
        : handedBack
          ? <div data-keep-clear="" className="border-t border-line bg-surface px-5 py-3"><SendBackToAgent projectId={detail.project_id} taskRef={detail.task_ref} answered={round.status === "answered"} /></div>
          : reopenable
            ? <ReopenBox key={detail.task_id} detail={detail} />
            : null}
    </>
  );
}

const LIST_WIDTH = 380;
const LIST_MIN = 280;
/** The view panel keeps at least this much room. */
const PANEL_MIN = 420;

/** Which projects have work in the timeline, with how many items wait in each. */
function projectsIn(items: ReviewItem[]) {
  const found = new Map<string, { id: string; name: string; waiting: number; total: number }>();
  for (const item of items) {
    const entry = found.get(item.project_id) ?? { id: item.project_id, name: item.project_name, waiting: 0, total: 0 };
    entry.total += 1;
    if (item.reviewed_at === null) entry.waiting += 1;
    found.set(item.project_id, entry);
  }
  return [...found.values()].sort((a, b) => b.waiting - a.waiting || a.name.localeCompare(b.name));
}

/** With nothing chosen, open the first task in a group that is shown: questions, then work, then reviewed. */
function firstShown(waiting: ReviewItem[], reviewed: ReviewItem[], folded: Folds): ReviewItem | undefined {
  return (folded.questions ? undefined : waiting.find((i) => i.question))
    ?? (folded.waiting ? undefined : waiting.find((i) => !i.question))
    ?? (folded.reviewed ? undefined : reviewed[0]);
}

/**
 * The Review screen: on the left, one line per task agents finished, from every project (or one);
 * on the right, the selected task's review and your comment box underneath. Drag the line between
 * them to give either side more room. It fills the whole window.
 */
export function ReviewScreen({ projectId, embedded = false }: { projectId?: string; embedded?: boolean }) {
  const timeline = useReviewTimeline(projectId);
  const [folded, fold] = useReviewFolds();
  const [params, setParams] = useSearchParams();
  const box = useRef<HTMLDivElement>(null);
  const [room, setRoom] = useState(1280);
  useEffect(() => {
    const element = box.current;
    if (!element) return;
    const measure = () => setRoom(element.clientWidth || 1280);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const listMax = Math.max(LIST_MIN, room - PANEL_MIN);
  const [listWidth, setListWidth] = usePaneWidth("moah.review.listWidth", LIST_WIDTH, LIST_MIN, listMax);
  const allWaiting = timeline.data?.waiting ?? [];
  const allReviewed = timeline.data?.reviewed ?? [];
  const projects = projectId ? [] : projectsIn([...allWaiting, ...allReviewed]);
  const only = projectId ? null : params.get("project");
  const shownProject = only && projects.some((p) => p.id === only) ? only : null;
  const waiting = shownProject ? allWaiting.filter((i) => i.project_id === shownProject) : allWaiting;
  const reviewed = shownProject ? allReviewed.filter((i) => i.project_id === shownProject) : allReviewed;
  const all = [...waiting, ...reviewed];
  const wanted = params.get("item");
  // A task changes key when it is decided ("task:…" becomes "review:…"), and the lists refresh a
  // moment later. Until then, stay on the same task instead of jumping to the top of the list.
  const shown = useRef<ReviewItem | null>(null);
  const last = shown.current;
  const item = all.find((i) => i.key === wanted)
    ?? (last ? all.find((i) => i.kind === last.kind && i.project_id === last.project_id && i.ref === last.ref) : undefined)
    ?? firstShown(waiting, reviewed, folded) ?? waiting[0] ?? reviewed[0] ?? null;
  shown.current = item;

  function select(next: ReviewItem | null) {
    setParams((current) => {
      const copy = new URLSearchParams(current);
      if (next) copy.set("item", next.key); else copy.delete("item");
      return copy;
    }, { replace: true });
  }

  function filter(project: string) {
    setParams((current) => {
      const copy = new URLSearchParams(current);
      if (project) copy.set("project", project); else copy.delete("project");
      copy.delete("item");
      return copy;
    }, { replace: true });
  }

  function decided(verdict: ReviewDecisionInput["verdict"], result: ReviewDetail) {
    if (!item) return;
    // Sent back or answered: stay on it, with the way to hand your words to an agent now.
    if (verdict !== "accept" && result.current.id) {
      setParams((current) => { const copy = new URLSearchParams(current); copy.set("item", `review:${result.current.id}`); return copy; }, { replace: true });
      return;
    }
    // On to the next piece of work waiting, the way a mail app moves on after archiving a message.
    const index = waiting.findIndex((i) => i.key === item.key);
    const rest = waiting.filter((i) => i.key !== item.key && !folded[i.question ? "questions" : "waiting"]);
    select(rest[Math.min(Math.max(index, 0), rest.length - 1)] ?? null);
  }

  // Every scrolling pane here is `relative`. Screen reader text is positioned absolutely, and in a
  // pane that isn't positioned it escapes the pane's scrolling and stretches the window below it.
  return (
    <div ref={box} className={`relative flex min-h-0 flex-col bg-canvas lg:flex-row ${embedded ? "h-[calc(100vh-13rem)] min-h-[36rem] overflow-hidden rounded-xl border border-line" : "h-screen"}`}
      style={{ ["--review-list" as string]: `${listWidth}px` }}>
      <aside aria-label={t("Review timeline")} className="relative max-h-[42vh] shrink-0 overflow-y-auto border-b border-line bg-surface/60 px-4 py-5 lg:max-h-none lg:w-[var(--review-list)] lg:border-b-0">
        {!embedded && (
          <div className="mb-4 px-1">
            <h1 className="text-2xl font-semibold tracking-tight text-ink">{t("Review")}</h1>
            <p className="mt-1 text-sm leading-6 text-ink-muted">{t("Tasks Claude Code and Codex finished, and questions they need you to answer. Accept moves a task to Done.")}</p>
          </div>
        )}
        {projects.length > 1 && (
          <label className="mb-4 flex items-center gap-2 px-1 text-xs font-semibold text-ink-muted">
            <span className="shrink-0">{t("Show")}</span>
            <select value={shownProject ?? ""} onChange={(event) => filter(event.target.value)}
              className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm font-medium text-ink focus-visible:outline-2 focus-visible:outline-forest">
              <option value="">{t("All projects ({count} waiting)", { count: allWaiting.length })}</option>
              {projects.map((p) => <option key={p.id} value={p.id}>{t("{project} ({count} waiting)", { project: p.name, count: p.waiting })}</option>)}
            </select>
          </label>
        )}
        {timeline.isPending ? <Loading label={t("Loading the review timeline")} />
          : timeline.isError ? <ErrorState title={t("The review timeline could not be loaded")} message={timeline.error.message} onRetry={() => void timeline.refetch()} />
          : <ReviewTimeline waiting={waiting} reviewed={reviewed} selected={item?.key ?? null} showProject={!projectId && !shownProject} onSelect={select} folded={folded} onFold={fold} />}
      </aside>
      <PaneResizer width={listWidth} min={LIST_MIN} max={listMax} fallback={LIST_WIDTH} onResize={setListWidth} label={t("Resize the task list")} />
      <section aria-label={t("Selected review")} className="flex min-h-0 min-w-0 flex-1 flex-col">
        {item?.kind === "task" ? <TaskPanel key={`${item.project_id}:${item.ref}`} item={item} onDecided={decided} />
          : item?.kind === "suggestion" ? <div className="relative min-h-0 flex-1 overflow-y-auto px-5 py-6 sm:px-8"><SuggestionPanel key={item.key} item={item} waitingHere={item.reviewed_at === null ? waiting.filter((i) => i.kind === "suggestion" && i.project_id === item.project_id).length : 0} /></div>
          : !timeline.isPending && (
            <div className="flex flex-1 items-center justify-center p-8">
              <EmptyState icon={<ClipboardCheck size={26} />} title={t("Nothing to review yet")}>
                {t("When Claude Code or Codex finishes a task, it lands here with what it did, what it didn't, and screenshots.")}
              </EmptyState>
            </div>
          )}
      </section>
    </div>
  );
}

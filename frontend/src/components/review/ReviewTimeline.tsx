import { useRef, type KeyboardEvent } from "react";
import { Camera, CircleCheck, CircleHelp, Lightbulb, MessageSquareReply, RotateCcw, Sparkles } from "lucide-react";
import type { ReviewItem } from "../../types/review";
import { statusLabels } from "../../types/task";
import { TaskStatusBadge } from "../tasks/TaskBits";
import { projectAccent, ProjectAvatar } from "../ui";
import { t, tp } from "../../lib/i18n";
import { AgentChip, exactly, when } from "./reviewBits";

function Verdict({ item }: { item: ReviewItem }) {
  if (item.verdict === "answered") {
    return <span className="inline-flex items-center gap-1 text-xs font-semibold text-info-ink"><MessageSquareReply size={13} aria-hidden="true" />{item.moved_to ? t("Moved to {status} on the board", { status: statusLabels[item.moved_to] }) : t("Answered")}</span>;
  }
  if (item.moved_to) {
    const accepted = item.verdict === "accepted";
    return <span className={`inline-flex items-center gap-1 text-xs font-semibold ${accepted ? "text-success-ink" : "text-danger-ink"}`}>{accepted ? <CircleCheck size={13} aria-hidden="true" /> : <RotateCcw size={13} aria-hidden="true" />}{t("Moved to {status} on the board", { status: statusLabels[item.moved_to] })}</span>;
  }
  if (item.verdict === "accepted") return <span className="inline-flex items-center gap-1 text-xs font-semibold text-success-ink"><CircleCheck size={13} aria-hidden="true" />{t("Accepted")}</span>;
  if (item.verdict === "rejected") return <span className="inline-flex items-center gap-1 text-xs font-semibold text-danger-ink"><RotateCcw size={13} aria-hidden="true" />{item.kind === "task" ? t("Rejected") : t("Dismissed")}</span>;
  return null;
}

function Row({ item, selected, showProject, onSelect }: { item: ReviewItem; selected: boolean; showProject: boolean; onSelect: () => void }) {
  const accent = projectAccent({ accent: item.project_accent });
  const project = { name: item.project_name, icon: item.project_icon, accent: item.project_accent };
  const reviewed = item.reviewed_at !== null;
  return (
    <li>
      <button
        type="button"
        data-review-key={item.key}
        onClick={onSelect}
        aria-current={selected ? "true" : undefined}
        className={`group relative block w-full overflow-hidden rounded-lg border py-2.5 pl-4 pr-3 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-forest ${selected ? "border-forest bg-sage-pale shadow-card" : "border-line bg-surface hover:border-line-hover hover:bg-canvas"} ${reviewed && !selected ? "opacity-90" : ""}`}
      >
        <span className="absolute inset-y-0 left-0 w-1" style={{ background: accent }} aria-hidden="true" />
        <span className="flex items-start gap-2">
          {showProject && <span className="mt-0.5"><ProjectAvatar project={project} size="small" /></span>}
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-1.5 text-xs text-ink-subtle">
              {item.kind === "suggestion" ? <Lightbulb size={12} className="text-special" aria-hidden="true" /> : null}
              <span className="font-medium">{item.ref}</span>
              {showProject && <span className="truncate">· {item.project_name}</span>}
              {item.kind === "suggestion" && <span className="rounded bg-special-soft px-1 font-semibold text-special-ink">{t("Suggestion")}</span>}
              {item.question && <span className="inline-flex items-center gap-0.5 rounded bg-warning-soft px-1 font-semibold text-warning-ink"><CircleHelp size={11} aria-hidden="true" />{t("Question")}</span>}
              {item.round > 1 && !item.question && <span className="rounded bg-warning-soft px-1 font-semibold text-warning-ink">{t("Round {count}", { count: item.round })}</span>}
            </span>
            <span className="mt-0.5 block line-clamp-2 text-sm font-semibold leading-5 text-ink">{item.title}</span>
            <span className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-subtle">
              {item.task_status && <TaskStatusBadge status={item.task_status} />}
              <AgentChip agent={item.agent} />
              <span title={exactly(item.done_at)}>{item.question ? t("Asked {when}", { when: when(item.done_at) }) : item.kind === "task" ? t("Done {when}", { when: when(item.done_at) }) : t("Sent {when}", { when: when(item.done_at) })}</span>
              {item.screenshots > 0 && <span className="inline-flex items-center gap-0.5" title={tp(item.screenshots, "{count} screenshot", "{count} screenshots")}><Camera size={12} aria-hidden="true" />{item.screenshots}<span className="sr-only">{tp(item.screenshots, "{count} screenshot", "{count} screenshots")}</span></span>}
              {item.generated && <span className="inline-flex items-center gap-0.5" title={item.question ? t("The agent asked nothing; Moah shows its last checkpoint") : t("The agent wrote no review; Moah shows its last checkpoint")}><Sparkles size={12} aria-hidden="true" />{t("From checkpoint")}</span>}
            </span>
            {reviewed && (
              <span className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-ink-subtle">
                <Verdict item={item} />
                <span title={exactly(item.reviewed_at)}>{item.question ? t("Answered {when}", { when: when(item.reviewed_at) }) : t("Reviewed {when}", { when: when(item.reviewed_at) })}</span>
              </span>
            )}
          </span>
        </span>
      </button>
    </li>
  );
}

function Count({ n, tone }: { n: number; tone: string }) {
  return <span className={`rounded-full px-1.5 text-xs font-bold leading-5 ${n ? tone : "bg-neutral-soft text-ink-muted"}`}>{n}</span>;
}

/**
 * The left column: everything agents finished, newest first. What waits for you comes first, with
 * agents' questions on top because their work is stuck until you answer; what you already decided
 * follows. Up and Down arrows (or J and K) move through the list.
 */
export function ReviewTimeline({ waiting, reviewed, selected, showProject, onSelect }: { waiting: ReviewItem[]; reviewed: ReviewItem[]; selected: string | null; showProject: boolean; onSelect: (item: ReviewItem) => void }) {
  const list = useRef<HTMLDivElement>(null);
  const questions = waiting.filter((item) => item.question);
  const work = waiting.filter((item) => !item.question);
  const all = [...questions, ...work, ...reviewed];
  const row = (item: ReviewItem) => <Row key={item.key} item={item} selected={item.key === selected} showProject={showProject} onSelect={() => onSelect(item)} />;

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const target = event.target as HTMLElement;
    if (target.closest("textarea, input")) return;
    const step = event.key === "ArrowDown" || event.key === "j" ? 1 : event.key === "ArrowUp" || event.key === "k" ? -1 : 0;
    if (!step || !all.length) return;
    event.preventDefault();
    const index = all.findIndex((item) => item.key === selected);
    const next = all[Math.min(all.length - 1, Math.max(0, index + step))];
    onSelect(next);
    list.current?.querySelector<HTMLButtonElement>(`[data-review-key="${CSS.escape(next.key)}"]`)?.focus();
  }

  return (
    <div ref={list} onKeyDown={onKeyDown} className="space-y-5">
      {questions.length > 0 && (
        <section aria-labelledby="review-questions">
          <h2 id="review-questions" className="mb-2 flex items-center gap-2 px-1 text-xs font-semibold uppercase tracking-wider text-warning-ink">
            {t("Needs your answer")}
            <Count n={questions.length} tone="bg-warning text-black" />
          </h2>
          <ul className="space-y-2" aria-label={t("Needs your answer")}>{questions.map(row)}</ul>
        </section>
      )}
      <section aria-labelledby="review-waiting">
        <h2 id="review-waiting" className="mb-2 flex items-center gap-2 px-1 text-xs font-semibold uppercase tracking-wider text-ink-muted">
          {t("Needs review")}
          <Count n={work.length} tone="bg-primary text-white" />
        </h2>
        {work.length
          ? <ul className="space-y-2" aria-label={t("Needs review")}>{work.map(row)}</ul>
          : <p className="flex items-center gap-2 rounded-lg border border-dashed border-line-strong px-3 py-4 text-sm text-ink-muted"><CircleCheck size={18} className="text-success" aria-hidden="true" />{questions.length ? t("No finished work waiting.") : t("You're all caught up.")}</p>}
      </section>
      <section aria-labelledby="review-done">
        <h2 id="review-done" className="mb-2 px-1 text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("Reviewed")}</h2>
        {reviewed.length
          ? <ul className="space-y-2" aria-label={t("Reviewed")}>{reviewed.map(row)}</ul>
          : <p className="px-1 text-sm text-ink-subtle">{t("Work you accept or reject is listed here.")}</p>}
      </section>
    </div>
  );
}

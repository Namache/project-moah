import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Camera, ChevronRight, CircleCheck, CircleHelp, Lightbulb, MessageSquareReply, RotateCcw } from "lucide-react";
import type { ReviewItem } from "../../types/review";
import { statusLabels } from "../../types/task";
import { TaskStatusBadge } from "../tasks/TaskBits";
import { projectAccent, ProjectAvatar } from "../ui";
import { readPref, writePref } from "../../lib/prefs";
import { t, tp } from "../../lib/i18n";
import { AgentChip, exactly, when } from "./reviewBits";

function Verdict({ item }: { item: ReviewItem }) {
  if (item.verdict === "answered") {
    return <span className="inline-flex items-center gap-1 text-xs font-semibold text-info-ink"><MessageSquareReply size={13} aria-hidden="true" />{item.moved_to === "chat" ? t("Answered in the chat") : item.moved_to ? t("Moved to {status} on the board", { status: statusLabels[item.moved_to] }) : t("Answered")}</span>;
  }
  if (item.moved_to && item.moved_to !== "chat") {
    const accepted = item.verdict === "accepted";
    return <span className={`inline-flex items-center gap-1 text-xs font-semibold ${accepted ? "text-success-ink" : "text-danger-ink"}`}>{accepted ? <CircleCheck size={13} aria-hidden="true" /> : <RotateCcw size={13} aria-hidden="true" />}{t("Moved to {status} on the board", { status: statusLabels[item.moved_to] })}</span>;
  }
  if (item.verdict === "accepted") return <span className="inline-flex items-center gap-1 text-xs font-semibold text-success-ink"><CircleCheck size={13} aria-hidden="true" />{t("Accepted")}</span>;
  if (item.verdict === "rejected") return <span className="inline-flex items-center gap-1 text-xs font-semibold text-danger-ink"><RotateCcw size={13} aria-hidden="true" />{item.kind === "task" ? t("Sent back") : t("Dismissed")}</span>;
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
  return <span className={`rounded-full px-1.5 text-xs font-bold leading-5 tabular-nums ${n ? tone : "bg-neutral-soft text-ink-muted"}`}>{n}</span>;
}

type Group = "questions" | "waiting" | "reviewed";
const FOLDED_KEY = "moah.review.folded";
// Reviewed starts folded: what waits for you matters first, and the list only grows.
const FOLDED_AT_FIRST: Record<Group, boolean> = { questions: false, waiting: false, reviewed: true };

function readFolded(): Record<Group, boolean> {
  try { return { ...FOLDED_AT_FIRST, ...(JSON.parse(readPref(FOLDED_KEY) ?? "{}") as Partial<Record<Group, boolean>>) }; } catch { return FOLDED_AT_FIRST; }
}

/** A heading that folds its list away, with how many items it holds. */
function Section({ title, hint, count, tone, headTone = "text-ink-muted", folded, onFold, children }: { title: string; hint?: string; count: number; tone: string; headTone?: string; folded: boolean; onFold: () => void; children: ReactNode }) {
  const id = useId();
  return (
    <section aria-labelledby={id}>
      <h2 id={id} className={hint && !folded ? "" : "mb-2"}>
        <button type="button" onClick={onFold} aria-expanded={!folded} aria-controls={`${id}-list`}
          className={`flex w-full items-center gap-1.5 rounded-md px-1 py-1 text-left text-xs font-semibold uppercase tracking-wider hover:bg-hover focus-visible:outline-2 focus-visible:outline-forest ${headTone}`}>
          <ChevronRight size={15} className={`shrink-0 transition-transform ${folded ? "" : "rotate-90"}`} aria-hidden="true" />
          <span>{title}</span>
          <Count n={count} tone={tone} />
          <span className="sr-only">{folded ? t("(folded, press to show)") : t("(press to fold)")}</span>
        </button>
      </h2>
      {hint && !folded && <p className="mb-2 pl-7 pr-1 text-xs text-ink-subtle">{hint}</p>}
      <div id={`${id}-list`} hidden={folded}>{children}</div>
    </section>
  );
}

/**
 * The left column: one line per task. What waits for you comes first, with agents' questions on
 * top because their work is stuck until you answer; what you already decided follows. Each group
 * folds away with its arrow, and stays as you left it. Up and Down arrows (or J and K) move through
 * the lines you can see.
 */
export function ReviewTimeline({ waiting, reviewed, selected, showProject, onSelect }: { waiting: ReviewItem[]; reviewed: ReviewItem[]; selected: string | null; showProject: boolean; onSelect: (item: ReviewItem) => void }) {
  const list = useRef<HTMLDivElement>(null);
  const [folded, setFolded] = useState(readFolded);
  const questions = waiting.filter((item) => item.question);
  const work = waiting.filter((item) => !item.question);
  const visible = [...(folded.questions ? [] : questions), ...(folded.waiting ? [] : work), ...(folded.reviewed ? [] : reviewed)];
  const row = (item: ReviewItem) => <Row key={item.key} item={item} selected={item.key === selected} showProject={showProject} onSelect={() => onSelect(item)} />;

  // A line chosen from outside the list (a notification, a link) shows: its group unfolds for
  // now, and the list scrolls to it.
  const groupOf = (key: string | null): Group | null => !key ? null
    : questions.some((i) => i.key === key) ? "questions" : work.some((i) => i.key === key) ? "waiting" : reviewed.some((i) => i.key === key) ? "reviewed" : null;
  const selectedGroup = groupOf(selected);
  useEffect(() => {
    if (selectedGroup && folded[selectedGroup]) setFolded((current) => ({ ...current, [selectedGroup]: false }));
  }, [selected, selectedGroup]);
  useEffect(() => {
    if (!selected) return;
    const row = list.current?.querySelector<HTMLElement>(`[data-review-key="${CSS.escape(selected)}"]`);
    row?.scrollIntoView?.({ block: "nearest" });
  }, [selected, folded]);

  function fold(group: Group) {
    setFolded((current) => {
      const next = { ...current, [group]: !current[group] };
      writePref(FOLDED_KEY, JSON.stringify(next));
      return next;
    });
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const target = event.target as HTMLElement;
    if (target.closest("textarea, input, select")) return;
    const step = event.key === "ArrowDown" || event.key === "j" ? 1 : event.key === "ArrowUp" || event.key === "k" ? -1 : 0;
    if (!step || !visible.length) return;
    event.preventDefault();
    const index = visible.findIndex((item) => item.key === selected);
    const next = visible[Math.min(visible.length - 1, Math.max(0, index + step))];
    onSelect(next);
    list.current?.querySelector<HTMLButtonElement>(`[data-review-key="${CSS.escape(next.key)}"]`)?.focus();
  }

  return (
    <div ref={list} onKeyDown={onKeyDown} className="space-y-4">
      {questions.length > 0 && (
        <Section title={t("Questions from agents")} hint={t("The agent stopped and waits for your reply.")} count={questions.length} tone="bg-warning text-black" headTone="text-warning-ink" folded={folded.questions} onFold={() => fold("questions")}>
          <ul className="space-y-2" aria-label={t("Questions from agents")}>{questions.map(row)}</ul>
        </Section>
      )}
      <Section title={t("Finished work to check")} hint={t("The agent says it's done. Accept it or send it back.")} count={work.length} tone="bg-primary text-white" folded={folded.waiting} onFold={() => fold("waiting")}>
        {work.length
          ? <ul className="space-y-2" aria-label={t("Finished work to check")}>{work.map(row)}</ul>
          : <p className="flex items-center gap-2 rounded-lg border border-dashed border-line-strong px-3 py-4 text-sm text-ink-muted"><CircleCheck size={18} className="text-success" aria-hidden="true" />{questions.length ? t("No finished work waiting.") : t("You're all caught up.")}</p>}
      </Section>
      <Section title={t("Reviewed")} count={reviewed.length} tone="bg-neutral-soft text-ink-muted" folded={folded.reviewed} onFold={() => fold("reviewed")}>
        {reviewed.length
          ? <ul className="space-y-2" aria-label={t("Reviewed")}>{reviewed.map(row)}</ul>
          : <p className="px-1 text-sm text-ink-subtle">{t("Work you accept or send back is listed here. You can still reopen accepted work from here.")}</p>}
      </Section>
    </div>
  );
}

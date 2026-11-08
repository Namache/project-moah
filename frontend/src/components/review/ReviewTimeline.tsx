import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Camera, ChevronRight, CircleCheck, CircleHelp, Layers, Lightbulb, MessageSquareReply, NotebookText, RotateCcw } from "lucide-react";
import type { ReviewItem } from "../../types/review";
import { statusLabels, type TaskStatus } from "../../types/task";
import { TaskStatusBadge } from "../tasks/TaskBits";
import { projectAccent, ProjectAvatar } from "../ui";
import { readPref, writePref } from "../../lib/prefs";
import { t, tp } from "../../lib/i18n";
import { agentName, exactly, when } from "./reviewBits";
import { TYPING, useSingleKeys } from "../../lib/reviewKeys";

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

/** The board column a waiting line is expected to be in: only a different one is worth a badge. */
function usual(item: ReviewItem): string | null {
  if (item.reviewed_at !== null) return null;
  return item.question ? "blocked" : "review";
}

function Row({ item, selected, showProject, onSelect }: { item: ReviewItem; selected: boolean; showProject: boolean; onSelect: () => void }) {
  const accent = projectAccent({ accent: item.project_accent, name: item.project_name });
  const project = { name: item.project_name, icon: item.project_icon, accent: item.project_accent };
  const reviewed = item.reviewed_at !== null;
  // Work that reached Review without the agent's own report: its page is pieced together from notes.
  const noReport = item.kind === "task" && !item.question && item.generated;
  const status = item.task_status && item.task_status !== usual(item) ? item.task_status : null;
  const time = item.question ? t("Asked {when}", { when: when(item.done_at) }) : item.kind === "task" ? t("Done {when}", { when: when(item.done_at) }) : t("Sent {when}", { when: when(item.done_at) });
  return (
    <li>
      <button
        type="button"
        data-review-key={item.key}
        onClick={onSelect}
        aria-current={selected ? "true" : undefined}
        className={`group relative block w-full overflow-hidden rounded-lg border py-2 pl-4 pr-3 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-forest ${selected ? "border-forest bg-sage-pale shadow-card" : "border-line bg-surface hover:border-line-hover hover:bg-canvas"} ${reviewed && !selected ? "opacity-90" : ""}`}
      >
        <span className="absolute inset-y-0 left-0 w-1" style={{ background: accent }} aria-hidden="true" />
        <span className="flex items-start gap-2">
          {showProject && <span className="mt-0.5"><ProjectAvatar project={project} size="small" /></span>}
          <span className="min-w-0 flex-1">
            <span className="block line-clamp-2 text-sm font-semibold leading-5 text-ink">{item.title}</span>
            <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-subtle">
              {item.kind === "suggestion" ? <Lightbulb size={12} className="text-special" aria-hidden="true" /> : null}
              <span className="font-medium">{item.ref}</span>
              {showProject && <span className="max-w-32 truncate">{item.project_name}</span>}
              {item.kind === "suggestion" && <span className="rounded bg-special-soft px-1 font-semibold text-special-ink">{t("Suggestion")}</span>}
              {item.question && <span className="inline-flex items-center gap-0.5 rounded bg-warning-soft px-1 font-semibold text-warning-ink"><CircleHelp size={11} aria-hidden="true" />{t("Question")}</span>}
              {item.round > 1 && !item.question && <span className="rounded bg-warning-soft px-1 font-semibold text-warning-ink">{t("Round {count}", { count: item.round })}</span>}
              {noReport && !reviewed && <span className="inline-flex items-center gap-0.5 rounded bg-neutral-soft px-1 font-semibold text-neutral-ink" title={t("The agent moved it to Review without its own report; the page is picked out of its notes.")}><NotebookText size={11} aria-hidden="true" />{t("No report")}</span>}
              {status && <TaskStatusBadge status={status as TaskStatus} />}
              {item.screenshots > 0 && <span className="inline-flex items-center gap-0.5" title={tp(item.screenshots, "{count} screenshot", "{count} screenshots")}><Camera size={12} aria-hidden="true" />{item.screenshots}<span className="sr-only">{tp(item.screenshots, "{count} screenshot", "{count} screenshots")}</span></span>}
              <span className="ml-auto whitespace-nowrap" title={exactly(item.done_at)}>{agentName(item.agent)}{reviewed ? "" : ` · ${time}`}</span>
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

export type Group = "questions" | "waiting" | "reviewed";
export type Folds = Record<Group, boolean>;
const FOLDED_KEY = "moah.review.folded";
// Reviewed starts folded: what waits for you matters first, and the list only grows.
const FOLDED_AT_FIRST: Record<Group, boolean> = { questions: false, waiting: false, reviewed: true };

function readFolded(): Folds {
  try { return { ...FOLDED_AT_FIRST, ...(JSON.parse(readPref(FOLDED_KEY) ?? "{}") as Partial<Folds>) }; } catch { return FOLDED_AT_FIRST; }
}

/**
 * Which groups are folded. Only the person's click on a group's arrow changes it: choosing a task,
 * a notification, accepting work or restarting the app never folds or unfolds a group. It is saved
 * at once, so it is the same the next time the app starts.
 */
export function useReviewFolds(): [Folds, (group: Group) => void] {
  const [folded, setFolded] = useState(readFolded);
  function fold(group: Group) {
    setFolded((current) => {
      const next = { ...current, [group]: !current[group] };
      writePref(FOLDED_KEY, JSON.stringify(next));
      return next;
    });
  }
  return [folded, fold];
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
 * folds away with its arrow, and stays as you left it until you press the arrow again, even when
 * the chosen task sits in a folded group. Up and Down arrows (or J and K) move through the lines
 * you can see.
 */
export function ReviewTimeline({ waiting, reviewed, selected, showProject, onSelect, folded, onFold }: { waiting: ReviewItem[]; reviewed: ReviewItem[]; selected: string | null; showProject: boolean; onSelect: (item: ReviewItem) => void; folded: Folds; onFold: (group: Group) => void }) {
  const list = useRef<HTMLDivElement>(null);
  const questions = waiting.filter((item) => item.question);
  const work = waiting.filter((item) => !item.question);
  const visible = [...(folded.questions ? [] : questions), ...(folded.waiting ? [] : work), ...(folded.reviewed ? [] : reviewed)];
  const row = (item: ReviewItem) => <Row key={item.key} item={item} selected={item.key === selected} showProject={showProject} onSelect={() => onSelect(item)} />;
  // Work one agent note covered together sits under one heading you can open as a whole.
  const blocks: ({ item: ReviewItem } | { batch: string; title: string; items: ReviewItem[] })[] = [];
  for (const item of work) {
    if (!item.batch) { blocks.push({ item }); continue; }
    const found = blocks.find((b) => "batch" in b && b.batch === item.batch);
    if (found && "batch" in found) found.items.push(item);
    else blocks.push({ batch: item.batch, title: item.batch_title ?? "", items: [item] });
  }

  // A chosen line scrolls into view when its group is shown.
  useEffect(() => {
    if (!selected) return;
    const row = list.current?.querySelector<HTMLElement>(`[data-review-key="${CSS.escape(selected)}"]`);
    row?.scrollIntoView?.({ block: "nearest" });
  }, [selected, folded]);

  // Up and Down (or J and K) move through the lines you can see, from anywhere on the screen
  // except while you type.
  const singleKeys = useSingleKeys();
  const move = useRef({ visible, selected, onSelect, singleKeys });
  move.current = { visible, selected, onSelect, singleKeys };
  useEffect(() => {
    function onKey(event: globalThis.KeyboardEvent) {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest(TYPING)) return;
      const { visible: shown, selected: current, onSelect: choose, singleKeys: letters } = move.current;
      // J and K are single-letter keys, off with the others in Settings; the arrows always work.
      const down = event.key === "ArrowDown" || (letters && event.key === "j");
      const up = event.key === "ArrowUp" || (letters && event.key === "k");
      const step = down ? 1 : up ? -1 : 0;
      if (!step || !shown.length) return;
      // Arrows keep scrolling the page when focus is outside the list.
      if (event.key.startsWith("Arrow") && !list.current?.contains(target)) return;
      event.preventDefault();
      const index = shown.findIndex((item) => item.key === current);
      const next = shown[Math.min(shown.length - 1, Math.max(0, index + step))];
      choose(next);
      if (list.current?.contains(target)) list.current.querySelector<HTMLButtonElement>(`[data-review-key="${CSS.escape(next.key)}"]`)?.focus();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div ref={list} className="space-y-4">
      {questions.length > 0 && (
        <Section title={t("Questions from agents")} hint={t("The agent stopped and waits for your reply.")} count={questions.length} tone="bg-warning text-black" headTone="text-warning-ink" folded={folded.questions} onFold={() => onFold("questions")}>
          <ul className="space-y-2" aria-label={t("Questions from agents")}>{questions.map(row)}</ul>
        </Section>
      )}
      <Section title={t("Finished work to check")} hint={t("The agent says it's done. Accept it or send it back.")} count={work.length} tone="bg-primary text-white" folded={folded.waiting} onFold={() => onFold("waiting")}>
        {work.length
          ? <ul className="space-y-2" aria-label={t("Finished work to check")}>{blocks.map((block) => "item" in block ? row(block.item) : (
              <li key={block.batch} className="rounded-xl border border-dashed border-line-strong p-1.5">
                <button type="button" data-review-key={block.batch} onClick={() => onSelect({ ...block.items[0], key: block.batch })} aria-current={selected === block.batch ? "true" : undefined}
                  className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs font-semibold focus-visible:outline-2 focus-visible:outline-forest ${selected === block.batch ? "bg-sage-pale text-forest" : "text-ink-muted hover:bg-hover"}`}>
                  <Layers size={14} className="shrink-0" aria-hidden="true" />
                  <span className="min-w-0 flex-1 truncate" title={block.title}>{block.title || t("One agent note")}</span>
                  <span className="shrink-0 rounded-full bg-primary px-1.5 leading-5 text-white tabular-nums">{block.items.length}</span>
                  <span className="shrink-0 text-forest">{t("Review together")}</span>
                </button>
                <ul className="mt-1.5 space-y-1.5" aria-label={t("Batch: {name}", { name: block.title || t("One agent note") })}>{block.items.map(row)}</ul>
              </li>
            ))}</ul>
          : <p className="flex items-center gap-2 rounded-lg border border-dashed border-line-strong px-3 py-4 text-sm text-ink-muted"><CircleCheck size={18} className="text-success" aria-hidden="true" />{questions.length ? t("No finished work waiting.") : t("You're all caught up.")}</p>}
      </Section>
      <Section title={t("Reviewed")} count={reviewed.length} tone="bg-neutral-soft text-ink-muted" folded={folded.reviewed} onFold={() => onFold("reviewed")}>
        {reviewed.length
          ? <ul className="space-y-2" aria-label={t("Reviewed")}>{reviewed.map(row)}</ul>
          : <p className="px-1 text-sm text-ink-subtle">{t("Work you accept or send back is listed here. You can still reopen accepted work from here.")}</p>}
      </Section>
    </div>
  );
}

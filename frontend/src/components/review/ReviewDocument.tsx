import { useEffect, useId, useState } from "react";
import { Link } from "react-router-dom";
import { Camera, ChevronLeft, ChevronRight, CircleCheck, CircleDashed, CircleHelp, CircleX, ClipboardList, ExternalLink, FileText, ListChecks, ListPlus, LoaderCircle, MessageSquareQuote, MessageSquareReply, PartyPopper, RotateCcw, Sparkles, X } from "lucide-react";
import type { FollowUp, ReviewDetail, ReviewFile, ReviewRound } from "../../types/review";
import { statusLabels } from "../../types/task";
import { TaskStatusBadge } from "../tasks/TaskBits";
import { useModalDialog } from "../../hooks/useModalDialog";
import { taskPath } from "../../lib/routes";
import { t, tp } from "../../lib/i18n";
import { Button, ProjectAvatar } from "../ui";
import { Markdown } from "./Markdown";
import { AgentChip, agentName, exactly, useReviewFileUrl, when } from "./reviewBits";

type Quote = (text: string) => void;

/** Making tasks from lines of the review: what was not done, or an unmet criterion. */
export interface FollowUpActions {
  /** Makes one line into a task in To do. */
  make: (text: string) => void;
  /** The line being made into a task right now. */
  making: string | null;
}

/** Your decision on this round; while it waits, the task's status says so. */
function StatusPill({ round }: { round: ReviewRound }) {
  if (round.status === "accepted") return <span className="inline-flex items-center gap-1 rounded-full bg-success-soft px-2.5 py-0.5 text-xs font-semibold text-success-ink"><CircleCheck size={13} aria-hidden="true" />{t("Accepted")}</span>;
  if (round.status === "rejected") return <span className="inline-flex items-center gap-1 rounded-full bg-danger-soft px-2.5 py-0.5 text-xs font-semibold text-danger-ink"><RotateCcw size={13} aria-hidden="true" />{t("Rejected")}</span>;
  if (round.status === "answered") return <span className="inline-flex items-center gap-1 rounded-full bg-info-soft px-2.5 py-0.5 text-xs font-semibold text-info-ink"><MessageSquareReply size={13} aria-hidden="true" />{t("Answered")}</span>;
  if (round.kind === "question") return <span className="inline-flex items-center gap-1 rounded-full bg-warning-soft px-2.5 py-0.5 text-xs font-semibold text-warning-ink"><CircleHelp size={13} aria-hidden="true" />{t("Question")}</span>;
  return null;
}

/** The task made from a line, with its column now. */
function FollowUpChip({ projectId, followUp }: { projectId: string; followUp: FollowUp }) {
  return (
    <Link to={taskPath(projectId, followUp.task_ref)} title={t("Open the follow-up task")}
      className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-md border border-line bg-surface px-1.5 py-0.5 text-xs font-semibold text-forest hover:border-forest">
      <ListPlus size={13} aria-hidden="true" />{followUp.task_ref}<span className="font-normal text-ink-muted">· {statusLabels[followUp.task_status]}</span>
    </Link>
  );
}

function MakeTaskButton({ text, actions, label = false }: { text: string; actions: FollowUpActions; label?: boolean }) {
  const busy = actions.making === text;
  return (
    <button type="button" onClick={() => actions.make(text)} disabled={actions.making !== null} title={t("Make a task from this line, in To do")} aria-label={t("Make a task from “{text}”", { text })}
      className="inline-flex shrink-0 items-center gap-1 rounded p-1 text-xs font-semibold text-ink-subtle hover:bg-hover hover:text-forest focus-visible:outline-2 focus-visible:outline-forest disabled:opacity-60">
      {busy ? <LoaderCircle size={15} className="animate-spin" aria-hidden="true" /> : <ListPlus size={15} aria-hidden="true" />}
      {label && <span>{t("Make a task")}</span>}
    </button>
  );
}

/**
 * One line of the Done or Not done list. Hover (or focus) shows a button that quotes it into your
 * comment; a Not done line can also become a task, and then shows that task.
 */
function Item({ text, done, onQuote, projectId, followUp, actions }: { text: string; done: boolean; onQuote?: Quote; projectId: string; followUp?: FollowUp; actions?: FollowUpActions }) {
  const Icon = done ? CircleCheck : CircleX;
  return (
    <li className="group flex items-start gap-2.5 rounded-md px-2 py-1.5 hover:bg-surface/70">
      <Icon size={17} className={`mt-0.5 shrink-0 ${done ? "text-success" : "text-danger"}`} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <Markdown text={text} className="leading-6 [&_p]:leading-6" />
        {!done && followUp && <div className="mt-1"><FollowUpChip projectId={projectId} followUp={followUp} /></div>}
      </div>
      {onQuote && (
        <button type="button" onClick={() => onQuote(text)} title={t("Quote in your comment")} aria-label={t("Quote “{text}” in your comment", { text })}
          className="shrink-0 rounded p-1 text-ink-subtle opacity-0 transition-opacity hover:bg-hover hover:text-forest focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-forest group-hover:opacity-100">
          <MessageSquareQuote size={15} aria-hidden="true" />
        </button>
      )}
      {!done && !followUp && actions && <MakeTaskButton text={text} actions={actions} />}
    </li>
  );
}

function Lightbox({ projectId, files, index, onIndex, onClose, onQuote }: { projectId: string; files: ReviewFile[]; index: number; onIndex: (index: number) => void; onClose: () => void; onQuote?: Quote }) {
  const ref = useModalDialog();
  const file = files[index];
  const url = useReviewFileUrl(projectId, file.id);
  const label = file.caption || file.filename;
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "ArrowRight") onIndex((index + 1) % files.length);
      if (event.key === "ArrowLeft") onIndex((index - 1 + files.length) % files.length);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, files.length, onIndex]);
  return (
    <dialog ref={ref} onCancel={(event) => { event.preventDefault(); onClose(); }} onClick={(event) => { if (event.target === event.currentTarget) onClose(); }} aria-label={label}
      className="m-auto h-[94vh] w-[94vw] max-w-none rounded-xl border border-line bg-surface p-0 text-ink shadow-dialog backdrop:bg-black/75">
      <div className="flex h-full flex-col">
        <div className="flex items-center gap-3 border-b border-line px-4 py-2.5">
          <Camera size={16} className="text-forest" aria-hidden="true" />
          <p className="min-w-0 flex-1 truncate text-sm font-semibold">{label}</p>
          <span className="text-xs tabular-nums text-ink-subtle">{t("{index} of {total}", { index: index + 1, total: files.length })}</span>
          {onQuote && <Button size="sm" variant="quiet" onClick={() => { onQuote(t("Screenshot “{name}”:", { name: label })); onClose(); }}><MessageSquareQuote size={15} aria-hidden="true" />{t("Comment on this")}</Button>}
          <Button size="icon" onClick={onClose} aria-label={t("Close image")}><X className="h-4 w-4" aria-hidden="true" /></Button>
        </div>
        <div className="relative flex min-h-0 flex-1 items-center justify-center bg-canvas p-4">
          {url ? <img src={url} alt={label} className="max-h-full max-w-full rounded-md object-contain shadow-card" /> : <p role="status" className="text-sm text-ink-muted">{t("Loading image…")}</p>}
          {files.length > 1 && <>
            <Button size="icon" className="absolute left-3 top-1/2 -translate-y-1/2 bg-surface/90" onClick={() => onIndex((index - 1 + files.length) % files.length)} aria-label={t("Previous screenshot")}><ChevronLeft className="h-5 w-5" aria-hidden="true" /></Button>
            <Button size="icon" className="absolute right-3 top-1/2 -translate-y-1/2 bg-surface/90" onClick={() => onIndex((index + 1) % files.length)} aria-label={t("Next screenshot")}><ChevronRight className="h-5 w-5" aria-hidden="true" /></Button>
          </>}
        </div>
      </div>
    </dialog>
  );
}

function Shot({ projectId, file, onOpen, small = false }: { projectId: string; file: ReviewFile; onOpen: () => void; small?: boolean }) {
  const url = useReviewFileUrl(projectId, file.id);
  const label = file.caption || file.filename;
  return (
    <li className="min-w-0">
      <button type="button" onClick={onOpen} aria-label={t("View {name}", { name: label })}
        className={`group block w-full overflow-hidden rounded-lg border border-line bg-canvas text-left shadow-card transition hover:-translate-y-0.5 hover:shadow-card-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-forest`}>
        <span className={`block ${small ? "aspect-[4/3]" : "aspect-video"} overflow-hidden bg-neutral-soft`}>
          {url ? <img src={url} alt="" className="h-full w-full object-cover object-top transition-transform group-hover:scale-[1.02]" /> : null}
        </span>
        {!small && <span className="block truncate border-t border-line px-2.5 py-1.5 text-xs text-ink-muted">{label}</span>}
      </button>
    </li>
  );
}

function TextFile({ projectId, file }: { projectId: string; file: ReviewFile }) {
  const url = useReviewFileUrl(projectId, file.id);
  return (
    <li>
      <a href={url ?? undefined} download={file.filename} className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs font-medium text-ink hover:border-forest hover:text-forest">
        <FileText size={14} aria-hidden="true" />{file.filename}
      </a>
    </li>
  );
}

function Gallery({ projectId, files, onQuote, small = false }: { projectId: string; files: ReviewFile[]; onQuote?: Quote; small?: boolean }) {
  const [open, setOpen] = useState<number | null>(null);
  const images = files.filter((f) => f.media_type.startsWith("image/"));
  const texts = files.filter((f) => !f.media_type.startsWith("image/"));
  return (
    <>
      {images.length > 0 && <ul className={`grid gap-3 ${small ? "grid-cols-[repeat(auto-fill,minmax(6rem,1fr))]" : "grid-cols-[repeat(auto-fill,minmax(14rem,1fr))]"}`}>{images.map((file, index) => <Shot key={file.id} projectId={projectId} file={file} small={small} onOpen={() => setOpen(index)} />)}</ul>}
      {texts.length > 0 && <ul className="mt-2 flex flex-wrap gap-2">{texts.map((file) => <TextFile key={file.id} projectId={projectId} file={file} />)}</ul>}
      {open !== null && images[open] && <Lightbox projectId={projectId} files={images} index={open} onIndex={setOpen} onClose={() => setOpen(null)} onQuote={onQuote} />}
    </>
  );
}

function Section({ title, icon: Icon, tone, count, children }: { title: string; icon: typeof CircleCheck; tone: "success" | "danger" | "info" | "special" | "neutral"; count?: number; children: React.ReactNode }) {
  const id = useId();
  const head = { success: "bg-success-soft text-success-ink", danger: "bg-danger-soft text-danger-ink", info: "bg-info-soft text-info-ink", special: "bg-special-soft text-special-ink", neutral: "bg-neutral-soft text-neutral-ink" }[tone];
  return (
    <section aria-labelledby={id} className="overflow-hidden rounded-xl border border-line bg-surface shadow-card">
      <h3 id={id} className={`flex items-center gap-2 px-4 py-2.5 text-sm font-semibold ${head}`}>
        <Icon size={16} aria-hidden="true" />{title}
        {count !== undefined && <span className="ml-auto rounded-full bg-surface/70 px-2 text-xs font-bold tabular-nums">{count}</span>}
      </h3>
      <div className="p-3">{children}</div>
    </section>
  );
}

/** An agent's question, in large type, with the answers it suggests. */
function QuestionBody({ detail, round, onPick, compact = false }: { detail: ReviewDetail; round: ReviewRound; onPick?: (answer: string) => void; compact?: boolean }) {
  return (
    <div className="space-y-4">
      <section aria-labelledby={`question-${round.round}`} className="overflow-hidden rounded-xl border border-warning/40 bg-gradient-to-br from-warning-soft to-surface shadow-card">
        <h3 id={`question-${round.round}`} className="flex items-center gap-2 px-5 pt-4 text-sm font-semibold text-warning-ink">
          <CircleHelp size={17} aria-hidden="true" />{t("{agent} needs your answer to go on", { agent: agentName(round.agent) })}
        </h3>
        <Markdown text={round.summary} className={`px-5 pb-4 pt-2 ${compact ? "" : "text-lg font-medium [&_p]:leading-8"}`} />
        {round.options.length > 0 && (
          <div className="border-t border-warning/30 bg-surface/60 px-5 py-3">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("Suggested answers")}</p>
            <ul className="flex flex-wrap gap-2">
              {round.options.map((option) => (
                <li key={option}>
                  {onPick
                    ? <button type="button" onClick={() => onPick(option)} className="rounded-lg border border-line-strong bg-surface px-3 py-1.5 text-left text-sm font-medium text-ink shadow-card hover:border-forest hover:text-forest focus-visible:outline-2 focus-visible:outline-forest">{option}</button>
                    : <span className="inline-block rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink-muted">{option}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
      {round.details && (
        <Section title={t("What the agent found")} icon={ClipboardList} tone="neutral">
          <Markdown text={round.details} className="px-1" />
        </Section>
      )}
      {round.screenshots.length > 0 && (
        <Section title={t("Screenshots")} icon={Camera} tone="special" count={round.screenshots.length}>
          <Gallery projectId={detail.project_id} files={round.screenshots} small={compact} />
        </Section>
      )}
    </div>
  );
}

function RoundBody({ detail, round, onQuote, followUps, compact = false }: { detail: ReviewDetail; round: ReviewRound; onQuote?: Quote; followUps?: FollowUpActions; compact?: boolean }) {
  const empty = round.generated && !round.summary && !round.done.length && !round.not_done.length && !round.details;
  const made = new Map(round.follow_ups.map((f) => [f.text, f]));
  const note = round.kind === "question"
    ? t("The agent marked this task Blocked without asking a question, so this is its last checkpoint. Answer what it needs below, or move the task on the board.")
    : empty ? t("The agent moved this task to review without writing anything down. Look at the task, or reject it and ask for a review.") : t("The agent didn't write a review, so this is its last checkpoint.");
  return (
    <div className="space-y-4">
      {round.generated && (
        <p className="flex items-start gap-2 rounded-lg bg-info-soft px-3 py-2 text-sm text-info-ink">
          <Sparkles size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
          {note}
        </p>
      )}
      {round.summary && (
        <div className="rounded-xl border border-line bg-gradient-to-br from-sage-pale to-surface px-5 py-4 shadow-card">
          <Markdown text={round.summary} className={compact ? "" : "text-base [&_p]:leading-7"} />
        </div>
      )}
      {(round.done.length > 0 || round.not_done.length > 0 || !round.generated) && (
        <div className="grid gap-4 xl:grid-cols-2">
          <Section title={t("Done")} icon={CircleCheck} tone="success" count={round.done.length}>
            {round.done.length ? <ul>{round.done.map((text, i) => <Item key={i} text={text} done onQuote={onQuote} projectId={detail.project_id} />)}</ul> : <p className="px-2 py-1 text-sm text-ink-subtle">{t("Nothing listed.")}</p>}
          </Section>
          <Section title={t("Not done")} icon={CircleX} tone="danger" count={round.not_done.length}>
            {round.not_done.length
              ? <ul>{round.not_done.map((text, i) => <Item key={i} text={text} done={false} onQuote={onQuote} projectId={detail.project_id} followUp={made.get(text)} actions={followUps} />)}</ul>
              : <p className="flex items-center gap-2 px-2 py-1 text-sm text-success-ink"><PartyPopper size={16} aria-hidden="true" />{t("Nothing left out, says the agent.")}</p>}
          </Section>
        </div>
      )}
      {round.screenshots.length > 0 && (
        <Section title={t("Screenshots")} icon={Camera} tone="special" count={round.screenshots.length}>
          <Gallery projectId={detail.project_id} files={round.screenshots} onQuote={onQuote} small={compact} />
        </Section>
      )}
      {round.how_to_check && (
        <Section title={t("How to check it")} icon={ListChecks} tone="info">
          <Markdown text={round.how_to_check} className="px-1" />
        </Section>
      )}
      {round.details && (
        <Section title={t("Details")} icon={ClipboardList} tone="neutral">
          <Markdown text={round.details} className="px-1" />
        </Section>
      )}
    </div>
  );
}

function Decision({ detail, round }: { detail: ReviewDetail; round: ReviewRound }) {
  if (round.status !== "accepted" && round.status !== "rejected" && round.status !== "answered") return null;
  const tone = { accepted: ["border-success bg-success-soft", "text-success-ink"], rejected: ["border-danger bg-danger-soft", "text-danger-ink"], answered: ["border-info bg-info-soft", "text-info-ink"] }[round.status];
  const Icon = { accepted: CircleCheck, rejected: RotateCcw, answered: MessageSquareReply }[round.status];
  const said = { accepted: t("You accepted this"), rejected: t("You rejected this"), answered: t("You answered") }[round.status];
  return (
    <section className={`rounded-xl border-l-4 px-4 py-3 ${tone[0]}`}>
      <h3 className={`flex flex-wrap items-center gap-2 text-sm font-semibold ${tone[1]}`}>
        <Icon size={16} aria-hidden="true" />
        {round.moved_to === "chat" ? t("You answered in the agent's chat") : round.moved_to ? t("You moved it to {status} on the board", { status: statusLabels[round.moved_to] }) : said}
        <span className="font-normal" title={exactly(round.reviewed_at)}>· {when(round.reviewed_at)}</span>
      </h3>
      {round.comment && <p className="mt-1.5 whitespace-pre-wrap text-sm leading-6 text-ink">{round.comment}</p>}
      {round.feedback.length > 0 && <div className="mt-2"><Gallery projectId={detail.project_id} files={round.feedback} small /></div>}
    </section>
  );
}

/** Ticking acceptance criteria while the work waits: Accept records the ticks. */
export interface CriteriaTicks {
  met: (id: string) => boolean;
  set: (id: string, met: boolean) => void;
}

function Criteria({ detail, ticks, followUps }: { detail: ReviewDetail; ticks?: CriteriaTicks; followUps?: FollowUpActions }) {
  const made = new Map(detail.current.follow_ups.map((f) => [f.text, f]));
  return (
    <Section title={t("Acceptance criteria")} icon={ListChecks} tone="neutral" count={detail.criteria.length}>
      {ticks && <p className="px-2 pb-1.5 text-xs leading-5 text-ink-muted">{t("Accepting records these ticks. Untick any that isn't met: it can become a follow-up task.")}</p>}
      <ul>{detail.criteria.map((c) => {
        const followUp = made.get(c.description);
        if (ticks) {
          const met = ticks.met(c.id);
          return (
            <li key={c.id} className="flex items-start gap-2.5 rounded-md px-2 py-1.5 text-sm leading-6 hover:bg-surface/70">
              <input id={`criterion-${c.id}`} type="checkbox" checked={met} onChange={(event) => ticks.set(c.id, event.target.checked)} className="mt-1 h-4 w-4 shrink-0 accent-forest" />
              <label htmlFor={`criterion-${c.id}`} className={`min-w-0 flex-1 cursor-pointer ${met ? "text-ink" : "text-danger-ink"}`}>{c.description}</label>
              {followUp && <FollowUpChip projectId={detail.project_id} followUp={followUp} />}
            </li>
          );
        }
        return (
          <li key={c.id} className="flex items-start gap-2.5 px-2 py-1.5 text-sm leading-6">
            {c.is_completed ? <CircleCheck size={17} className="mt-0.5 shrink-0 text-success" aria-label={t("Ticked")} /> : <CircleDashed size={17} className="mt-0.5 shrink-0 text-ink-subtle" aria-label={t("Not ticked")} />}
            <span className={`min-w-0 flex-1 ${c.is_completed ? "text-ink" : "text-ink-muted"}`}>{c.description}</span>
            {!c.is_completed && (followUp ? <FollowUpChip projectId={detail.project_id} followUp={followUp} /> : followUps ? <MakeTaskButton text={c.description} actions={followUps} label /> : null)}
          </li>
        );
      })}</ul>
    </Section>
  );
}

/**
 * The view panel: what the agent did and did not do, in colour, with its screenshots, or the
 * question it needs answered. Any line can be quoted into your comment, and what was left can
 * become tasks. Earlier rounds of a task that came back are folded underneath.
 */
export function ReviewDocument({ detail, project, onQuote, onPick, ticks, followUps }: { detail: ReviewDetail; project: { name: string; icon: string | null; accent: string | null }; onQuote?: Quote; onPick?: (answer: string) => void; ticks?: CriteriaTicks; followUps?: FollowUpActions }) {
  const round = detail.current;
  const waiting = round.status === "pending";
  const question = round.kind === "question";
  const doneCriteria = detail.criteria.filter((c) => (ticks ? ticks.met(c.id) : c.is_completed)).length;
  return (
    <article aria-labelledby="review-title" className="space-y-5">
      <header>
        <p className="flex flex-wrap items-center gap-2 text-xs text-ink-subtle">
          <ProjectAvatar project={project} size="small" />
          <span className="font-medium text-ink-muted">{detail.project_name}</span>
          <span>·</span>
          <Link to={taskPath(detail.project_id, detail.task_ref)} className="inline-flex items-center gap-1 font-semibold text-forest hover:underline">{detail.task_ref}<ExternalLink size={12} aria-hidden="true" /><span className="sr-only">{t("Open the task")}</span></Link>
        </p>
        <h2 id="review-title" className="mt-1.5 text-2xl font-semibold leading-tight tracking-tight text-ink">{detail.task_title}</h2>
        <div className="mt-2.5 flex flex-wrap items-center gap-2 text-xs text-ink-muted">
          <TaskStatusBadge status={detail.task_status} />
          {(!waiting || question) && <StatusPill round={round} />}
          {round.round > 1 && !question && <span className="rounded-full bg-warning-soft px-2.5 py-0.5 font-semibold text-warning-ink">{t("Round {count}", { count: round.round })}</span>}
          <AgentChip agent={round.agent} />
          <span title={exactly(round.created_at)}>{question ? t("{agent} asked {when}", { agent: agentName(round.agent), when: when(round.created_at) }) : t("{agent} finished it {when}", { agent: agentName(round.agent), when: when(round.created_at) })}</span>
        </div>
        {!question && <div className="mt-3 flex flex-wrap gap-2 text-xs font-semibold">
          <span className="inline-flex items-center gap-1 rounded-lg bg-success-soft px-2 py-1 text-success-ink"><CircleCheck size={13} aria-hidden="true" />{tp(round.done.length, "{count} done", "{count} done")}</span>
          <span className={`inline-flex items-center gap-1 rounded-lg px-2 py-1 ${round.not_done.length ? "bg-danger-soft text-danger-ink" : "bg-neutral-soft text-neutral-ink"}`}><CircleX size={13} aria-hidden="true" />{tp(round.not_done.length, "{count} not done", "{count} not done")}</span>
          <span className="inline-flex items-center gap-1 rounded-lg bg-special-soft px-2 py-1 text-special-ink"><Camera size={13} aria-hidden="true" />{tp(round.screenshots.length, "{count} screenshot", "{count} screenshots")}</span>
          {detail.criteria.length > 0 && <span className="inline-flex items-center gap-1 rounded-lg bg-info-soft px-2 py-1 text-info-ink"><ListChecks size={13} aria-hidden="true" />{t("{done} of {total} criteria ticked", { done: doneCriteria, total: detail.criteria.length })}</span>}
          {round.follow_ups.length > 0 && <span className="inline-flex items-center gap-1 rounded-lg bg-neutral-soft px-2 py-1 text-neutral-ink"><ListPlus size={13} aria-hidden="true" />{tp(round.follow_ups.length, "{count} follow-up task", "{count} follow-up tasks")}</span>}
        </div>}
      </header>

      <Decision detail={detail} round={round} />
      {question && !round.generated
        ? <QuestionBody detail={detail} round={round} onPick={waiting ? onPick : undefined} />
        : <RoundBody detail={detail} round={round} onQuote={waiting ? onQuote : undefined} followUps={followUps} />}

      {detail.criteria.length > 0 && !question && <Criteria detail={detail} ticks={ticks} followUps={followUps} />}

      {detail.earlier.length > 0 && (
        <section aria-labelledby="review-earlier">
          <h3 id="review-earlier" className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("Earlier rounds")}</h3>
          <div className="space-y-2">
            {detail.earlier.map((earlier) => (
              <details key={earlier.round} className="group rounded-xl border border-line bg-surface shadow-card">
                <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 px-4 py-2.5 text-sm focus-visible:outline-2 focus-visible:outline-forest">
                  <ChevronRight size={15} className="text-ink-subtle transition-transform group-open:rotate-90" aria-hidden="true" />
                  <span className="font-semibold text-ink">{t("Round {count}", { count: earlier.round })}</span>
                  <StatusPill round={earlier} />
                  <span className="text-xs text-ink-subtle">{when(earlier.reviewed_at ?? earlier.created_at)}</span>
                  {earlier.comment && <span className="min-w-0 flex-1 truncate text-xs text-ink-muted">“{earlier.comment}”</span>}
                </summary>
                <div className="space-y-4 border-t border-line p-4">
                  <Decision detail={detail} round={earlier} />
                  {earlier.kind === "question" && !earlier.generated ? <QuestionBody detail={detail} round={earlier} compact /> : <RoundBody detail={detail} round={earlier} compact />}
                </div>
              </details>
            ))}
          </div>
        </section>
      )}
    </article>
  );
}

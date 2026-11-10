import { Link } from "react-router-dom";
import { Camera, ChevronRight, CircleCheck, CircleX, ClipboardList, ExternalLink, ListChecks, ListPlus, MessageSquareReply, NotebookText, RotateCcw } from "lucide-react";
import type { CheckpointNote, ReviewDetail, ReviewRound } from "../../types/review";
import { statusLabels } from "../../types/task";
import { TaskStatusBadge } from "../tasks/TaskBits";
import { taskPath } from "../../lib/routes";
import { t, tp } from "../../lib/i18n";
import { ProjectAvatar } from "../ui";
import { Markdown } from "./Markdown";
import { AgentChip, type Quote, agentName, exactly, when } from "./reviewBits";
import { Gallery } from "./ReviewFiles";
import { Section, StatusPill, hasAccount } from "./ReviewFrames";
import { type CriteriaTicks, type FollowUpActions, QuestionBody, WorkBody } from "./ReviewWork";

/** The task as it was asked. Folded under an account, with its first line showing; open when it is all there is. */
function Asked({ detail, open }: { detail: ReviewDetail; open: boolean }) {
  const text = detail.task_description?.trim();
  const body = text ? <Markdown text={text} className="px-1" /> : <p className="px-1 text-sm text-ink-subtle">{t("This task has no description.")}</p>;
  if (open) return <Section title={t("What was asked")} icon={ClipboardList} tone="neutral">{body}</Section>;
  if (!text) return null;
  const preview = text.split("\n").map((line) => line.replace(/^[#>*\-\s]+/, "").trim()).find(Boolean) ?? "";
  return (
    <details className="group rounded-xl border border-line bg-surface shadow-card">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-2.5 text-sm focus-visible:outline-2 focus-visible:outline-forest">
        <ChevronRight size={15} className="shrink-0 text-ink-subtle transition-transform group-open:rotate-90" aria-hidden="true" />
        <ClipboardList size={15} className="shrink-0 text-ink-muted" aria-hidden="true" />
        <span className="shrink-0 font-semibold text-ink-muted">{t("What was asked")}</span>
        <span className="min-w-0 flex-1 truncate text-ink-subtle group-open:hidden">{preview}</span>
      </summary>
      <div className="border-t border-line px-3 py-3">{body}</div>
    </details>
  );
}

function NoteField({ label, text }: { label: string; text: string }) {
  if (!text.trim()) return null;
  return <div><p className="mb-0.5 text-xs font-semibold uppercase tracking-wider text-ink-muted">{label}</p><Markdown text={text} /></div>;
}

/** The checkpoints a drafted account was picked from, whole: to see what was left out, or why. */
function FullNotes({ notes }: { notes: CheckpointNote[] }) {
  return (
    <details className="group rounded-xl border border-line bg-surface shadow-card">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-2.5 text-sm font-semibold text-ink-muted focus-visible:outline-2 focus-visible:outline-forest">
        <ChevronRight size={15} className="text-ink-subtle transition-transform group-open:rotate-90" aria-hidden="true" />
        <NotebookText size={15} aria-hidden="true" />{tp(notes.length, "The agent's full note", "The agent's full notes")}
        <span className="rounded-full bg-neutral-soft px-2 text-xs font-bold tabular-nums text-neutral-ink">{notes.length}</span>
      </summary>
      <ol className="divide-y divide-line border-t border-line">
        {notes.map((note, i) => (
          <li key={i} className="space-y-2 px-4 py-3 text-sm">
            <p className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-ink">{note.title}</span>
              <span className="text-xs text-ink-subtle" title={exactly(note.created_at)}>{when(note.created_at)}</span>
              {!note.filed_here && <span className="rounded-md bg-neutral-soft px-1.5 py-0.5 text-xs text-neutral-ink">{t("Filed under another task")}</span>}
            </p>
            <NoteField label={t("Summary")} text={note.summary} />
            <NoteField label={t("Done")} text={note.completed_work} />
            <NoteField label={t("Left")} text={note.remaining_work} />
            <NoteField label={t("Problems")} text={note.problems} />
            <NoteField label={t("Next steps")} text={note.next_steps} />
          </li>
        ))}
      </ol>
    </details>
  );
}

function Decision({ detail, round }: { detail: ReviewDetail; round: ReviewRound }) {
  if (round.status !== "accepted" && round.status !== "rejected" && round.status !== "answered") return null;
  const tone = { accepted: ["border-success bg-success-soft", "text-success-ink"], rejected: ["border-danger bg-danger-soft", "text-danger-ink"], answered: ["border-info bg-info-soft", "text-info-ink"] }[round.status];
  const Icon = { accepted: CircleCheck, rejected: RotateCcw, answered: MessageSquareReply }[round.status];
  const said = { accepted: t("You accepted this"), rejected: t("You sent this back"), answered: t("You answered") }[round.status];
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
          <span title={exactly(round.created_at)}>{question ? t("{agent} asked {when}", { agent: agentName(round.agent), when: when(round.created_at) }) : round.generated ? t("Moved to Review {when}", { when: when(round.created_at) }) : t("{agent} finished it {when}", { agent: agentName(round.agent), when: when(round.created_at) })}</span>
        </div>
        {!question && hasAccount(round) && <div className="mt-3 flex flex-wrap gap-2 text-xs font-semibold">
          <span className="inline-flex items-center gap-1 rounded-lg bg-success-soft px-2 py-1 text-success-ink"><CircleCheck size={13} aria-hidden="true" />{tp(round.done.length, "{count} done", "{count} done")}</span>
          {(round.not_done.length > 0 || !round.generated) && <span className={`inline-flex items-center gap-1 rounded-lg px-2 py-1 ${round.not_done.length ? "bg-danger-soft text-danger-ink" : "bg-neutral-soft text-neutral-ink"}`}><CircleX size={13} aria-hidden="true" />{tp(round.not_done.length, "{count} not done", "{count} not done")}</span>}
          {round.screenshots.length > 0 && <span className="inline-flex items-center gap-1 rounded-lg bg-special-soft px-2 py-1 text-special-ink"><Camera size={13} aria-hidden="true" />{tp(round.screenshots.length, "{count} screenshot", "{count} screenshots")}</span>}
          {detail.criteria.length > 0 && <span className="inline-flex items-center gap-1 rounded-lg bg-info-soft px-2 py-1 text-info-ink"><ListChecks size={13} aria-hidden="true" />{t("{done} of {total} criteria ticked", { done: doneCriteria, total: detail.criteria.length })}</span>}
          {round.follow_ups.length > 0 && <span className="inline-flex items-center gap-1 rounded-lg bg-neutral-soft px-2 py-1 text-neutral-ink"><ListPlus size={13} aria-hidden="true" />{tp(round.follow_ups.length, "{count} follow-up task", "{count} follow-up tasks")}</span>}
        </div>}
      </header>

      <Decision detail={detail} round={round} />
      {question && !round.generated
        ? <QuestionBody detail={detail} round={round} onPick={waiting ? onPick : undefined} />
        : <WorkBody detail={detail} round={round} onQuote={waiting ? onQuote : undefined} followUps={followUps} ticks={ticks} />}

      <Asked detail={detail} open={!question && !hasAccount(round)} />
      {round.generated && round.notes && round.notes.length > 0 && <FullNotes notes={round.notes} />}

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
                  {earlier.kind === "question" && !earlier.generated ? <QuestionBody detail={detail} round={earlier} compact /> : <WorkBody detail={detail} round={earlier} compact />}
                </div>
              </details>
            ))}
          </div>
        </section>
      )}
    </article>
  );
}

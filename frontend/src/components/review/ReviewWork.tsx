/** What a round says: the work done and left, the criteria to check, and the question asked. */
import { Link } from "react-router-dom";
import { ArrowRight, Camera, CircleCheck, CircleDashed, CircleHelp, CircleX, ClipboardList, ListChecks, ListPlus, ListTodo, LoaderCircle, MessageSquareQuote, PartyPopper } from "lucide-react";
import type { FollowUp, ReviewDetail, ReviewRound } from "../../types/review";
import { statusLabels } from "../../types/task";
import { taskPath } from "../../lib/routes";
import { t } from "../../lib/i18n";
import { Markdown } from "./Markdown";
import { type Quote, agentName } from "./reviewBits";
import { Gallery } from "./ReviewFiles";
import { Frame, Section, Verdict, hasAccount } from "./ReviewFrames";

/** Making tasks from lines of the review: what was not done, or an unmet criterion. */
export interface FollowUpActions {
  /** Makes one line into a task in To do. */
  make: (text: string) => void;
  /** The line being made into a task right now. */
  making: string | null;
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
      className={`inline-flex shrink-0 items-center gap-1 rounded p-1 text-xs font-semibold text-ink-subtle hover:bg-hover hover:text-forest focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-forest disabled:opacity-60 ${label || busy ? "" : "opacity-0 group-hover:opacity-100"}`}>
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

/** An agent's question, in large type, with the answers it suggests. */
export function QuestionBody({ detail, round, onPick, compact = false }: { detail: ReviewDetail; round: ReviewRound; onPick?: (answer: string) => void; compact?: boolean }) {
  return (
    <div className="space-y-4">
      <section aria-labelledby={`question-${round.round}`} className="overflow-hidden rounded-xl border border-warning/40 bg-gradient-to-br from-warning-soft to-surface shadow-card">
        <h3 id={`question-${round.round}`} className="flex items-center gap-2 px-5 pt-4 text-sm font-semibold text-warning-ink">
          <CircleHelp size={17} aria-hidden="true" />{round.from_note ? t("{agent} is waiting for you", { agent: agentName(round.agent) }) : t("{agent} needs your answer to go on", { agent: agentName(round.agent) })}
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
        <Section title={round.from_note ? t("From the agent's note") : t("What the agent found")} icon={ClipboardList} tone="neutral">
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

/** Ticking acceptance criteria while the work waits: Accept records the ticks. */
export interface CriteriaTicks {
  met: (id: string) => boolean;
  set: (id: string, met: boolean) => void;
}

/** What the person checks before deciding: the agent's "how to check" and the task's criteria. */
function CheckFrame({ detail, round, ticks, followUps, criteria }: { detail: ReviewDetail; round: ReviewRound; ticks?: CriteriaTicks; followUps?: FollowUpActions; criteria: boolean }) {
  const list = criteria ? detail.criteria : [];
  if (!round.how_to_check && list.length === 0) return null;
  const made = new Map(detail.current.follow_ups.map((f) => [f.text, f]));
  return (
    <Frame tone="warning" title={t("For you to check")} icon={ListChecks}>
      {round.how_to_check && <Markdown text={round.how_to_check} className="px-2 pb-1" />}
      {list.length > 0 && (
        <div className={round.how_to_check ? "mt-2 border-t border-line pt-2" : ""}>
          <p className="px-2 pb-1 text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("Acceptance criteria")}</p>
          {ticks && <p className="px-2 pb-1.5 text-xs leading-5 text-ink-muted">{t("Untick any that isn't met. Accept or Send back records your ticks.")}</p>}
          <ul>{list.map((c) => {
            const followUp = made.get(c.description);
            if (ticks) {
              const met = ticks.met(c.id);
              return (
                <li key={c.id} className="flex items-start gap-2.5 rounded-md px-2 py-1.5 text-sm leading-6 hover:bg-hover">
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
        </div>
      )}
    </Frame>
  );
}

/**
 * The agent's account of the work: Done, Not done, what to check, what it plans next. Drawn from
 * its report, or picked out of its checkpoint notes when it wrote none.
 */
export function WorkBody({ detail, round, onQuote, followUps, ticks, compact = false }: { detail: ReviewDetail; round: ReviewRound; onQuote?: Quote; followUps?: FollowUpActions; ticks?: CriteriaTicks; compact?: boolean }) {
  const made = new Map(round.follow_ups.map((f) => [f.text, f]));
  const steps = round.next_steps ?? [];
  return (
    <div className="space-y-6">
      {!compact && <Verdict round={round} />}
      {round.summary && (
        <div className="rounded-xl border border-line bg-gradient-to-br from-sage-pale to-surface px-5 py-4 shadow-card">
          <Markdown text={round.summary} className={compact ? "" : "text-base [&_p]:leading-7"} />
        </div>
      )}
      {hasAccount(round) && (
        <>
          <Frame tone="success" title={t("Done")} icon={CircleCheck} count={round.done.length}>
            {round.done.length ? <ul>{round.done.map((text, i) => <Item key={i} text={text} done onQuote={onQuote} projectId={detail.project_id} />)}</ul> : <p className="px-2 py-1 text-sm text-ink-subtle">{t("Nothing listed.")}</p>}
          </Frame>
          <Frame tone={round.not_done.length ? "danger" : "neutral"} title={t("Not done")} icon={CircleX} count={round.not_done.length}>
            {round.not_done.length
              ? <ul>{round.not_done.map((text, i) => <Item key={i} text={text} done={false} onQuote={onQuote} projectId={detail.project_id} followUp={made.get(text)} actions={followUps} />)}</ul>
              : round.generated
                // Notes that don't mention leftovers are not a promise that nothing is left.
                ? <p className="flex items-center gap-2 px-2 py-1 text-sm text-ink-muted"><CircleHelp size={16} aria-hidden="true" />{t("Its notes don't say what is left. Check the task before you accept.")}</p>
                : <p className="flex items-center gap-2 px-2 py-1 text-sm text-success-ink"><PartyPopper size={16} aria-hidden="true" />{t("Nothing left out, says the agent.")}</p>}
          </Frame>
        </>
      )}
      <CheckFrame detail={detail} round={round} ticks={ticks} followUps={followUps} criteria={!compact} />
      {steps.length > 0 && (
        <Frame tone="neutral" title={t("What the agent plans next")} icon={ListTodo} count={steps.length}>
          <ul>{steps.map((text, i) => (
            <li key={i} className="flex items-start gap-2.5 px-2 py-1.5"><ArrowRight size={16} className="mt-1 shrink-0 text-ink-subtle" aria-hidden="true" /><Markdown text={text} className="min-w-0 flex-1 leading-6 [&_p]:leading-6" /></li>
          ))}</ul>
        </Frame>
      )}
      {round.screenshots.length > 0 && (
        <Section title={t("Screenshots")} icon={Camera} tone="special" count={round.screenshots.length}>
          <Gallery projectId={detail.project_id} files={round.screenshots} onQuote={onQuote} small={compact} />
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

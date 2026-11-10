/** The framed parts of a review: sections, coloured frames, the round's status and the verdict. */
import { useId } from "react";
import { CircleAlert, CircleCheck, CircleHelp, MessageSquareReply, NotebookText, RotateCcw } from "lucide-react";
import type { ReviewRound } from "../../types/review";
import { t, tp } from "../../lib/i18n";
import { agentName } from "./reviewBits";

/** Your decision on this round; while it waits, the task's status says so. */
export function StatusPill({ round }: { round: ReviewRound }) {
  if (round.status === "accepted") return <span className="inline-flex items-center gap-1 rounded-full bg-success-soft px-2.5 py-0.5 text-xs font-semibold text-success-ink"><CircleCheck size={13} aria-hidden="true" />{t("Accepted")}</span>;
  if (round.status === "rejected") return <span className="inline-flex items-center gap-1 rounded-full bg-danger-soft px-2.5 py-0.5 text-xs font-semibold text-danger-ink"><RotateCcw size={13} aria-hidden="true" />{t("Sent back")}</span>;
  if (round.status === "answered") return <span className="inline-flex items-center gap-1 rounded-full bg-info-soft px-2.5 py-0.5 text-xs font-semibold text-info-ink"><MessageSquareReply size={13} aria-hidden="true" />{t("Answered")}</span>;
  if (round.kind === "question") return <span className="inline-flex items-center gap-1 rounded-full bg-warning-soft px-2.5 py-0.5 text-xs font-semibold text-warning-ink"><CircleHelp size={13} aria-hidden="true" />{t("Question")}</span>;
  return null;
}

export function Section({ title, icon: Icon, tone, count, children }: { title: string; icon: typeof CircleCheck; tone: "success" | "danger" | "info" | "special" | "neutral"; count?: number; children: React.ReactNode }) {
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

type FrameTone = "success" | "danger" | "warning" | "neutral";

const FRAME_TONES: Record<FrameTone, { box: string; label: string }> = {
  success: { box: "border-success/50", label: "border-success/50 bg-success-soft text-success-ink" },
  danger: { box: "border-danger/50", label: "border-danger/50 bg-danger-soft text-danger-ink" },
  warning: { box: "border-warning/60", label: "border-warning/60 bg-warning-soft text-warning-ink" },
  neutral: { box: "border-line-strong", label: "border-line-strong bg-neutral-soft text-neutral-ink" },
};

/** A frame with its name on the top border, like the Done and Not done boxes of an agent's summary. */
export function Frame({ tone, title, icon: Icon, count, children }: { tone: FrameTone; title: string; icon: typeof CircleCheck; count?: number; children: React.ReactNode }) {
  const id = useId();
  const tones = FRAME_TONES[tone];
  return (
    <section aria-labelledby={id} className={`relative rounded-xl border bg-surface px-2 pb-2 pt-5 shadow-card ${tones.box}`}>
      <h3 id={id} className={`absolute -top-3 left-3 inline-flex items-center gap-1.5 rounded-md border px-2.5 py-0.5 text-xs font-semibold ${tones.label}`}>
        <Icon size={13} aria-hidden="true" />{title}
        {count !== undefined && <span className="font-bold tabular-nums opacity-75">{count}</span>}
      </h3>
      {children}
    </section>
  );
}

/** Whether the agent's account has anything in its lists: a report always counts. */
export function hasAccount(round: ReviewRound): boolean {
  return !round.generated || round.done.length + round.not_done.length + (round.next_steps?.length ?? 0) > 0;
}

/** One line on where the work stands, and where the lines below come from. */
export function Verdict({ round }: { round: ReviewRound }) {
  const agent = agentName(round.agent);
  const left = round.not_done.length;
  let tone = "bg-info-soft text-info-ink";
  let Icon: typeof CircleCheck = NotebookText;
  let text: string;
  let note: string | null = null;
  if (!round.generated) {
    tone = left ? "bg-warning-soft text-warning-ink" : "bg-success-soft text-success-ink";
    Icon = left ? CircleAlert : CircleCheck;
    text = left
      ? tp(left, "{agent} says it's done, with {count} thing left.", "{agent} says it's done, with {count} things left.", { agent })
      : t("{agent} says it's done, with nothing left.", { agent });
  } else if (hasAccount(round)) {
    text = t("{agent} wrote no report, so this is picked out of its notes on the task.", { agent });
    if (round.left_out) note = t("Lines about other tasks are left out.");
  } else if (round.notes?.length) {
    tone = "bg-neutral-soft text-neutral-ink";
    text = t("{agent} wrote no report, and its notes don't say what it did on this task. Check the task itself below.", { agent });
  } else {
    tone = "bg-neutral-soft text-neutral-ink";
    text = t("{agent} moved this task to Review without a report or notes. Check the task itself below.", { agent });
  }
  return (
    <p className={`flex items-start gap-2 rounded-lg px-3 py-2 text-sm font-medium ${tone}`}>
      <Icon size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
      <span>{text}{note && <span className="font-normal"> {note}</span>}</span>
    </p>
  );
}

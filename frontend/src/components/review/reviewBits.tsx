import { useEffect, useState } from "react";
import { Bot, UserRound } from "lucide-react";
import { reviewsApi } from "../../api/reviews";
import { locale, t } from "../../lib/i18n";
import { toneClasses, type Tone } from "../ui";

const AGENTS: Record<string, { name: string; tone: Tone }> = {
  claude: { name: "Claude Code", tone: "warning" },
  codex: { name: "Codex", tone: "info" },
};

/** The name a person knows an agent by: "claude" is Claude Code. */
export function agentName(agent: string): string {
  if (agent === "human") return t("You");
  if (agent === "agent") return t("An agent");
  return AGENTS[agent.toLowerCase()]?.name ?? agent;
}

/** Who did the work, as a small coloured chip: Claude Code warm, Codex blue. */
export function AgentChip({ agent, className = "" }: { agent: string; className?: string }) {
  const known = AGENTS[agent.toLowerCase()];
  const tone: Tone = known?.tone ?? (agent === "human" ? "neutral" : "special");
  const Icon = agent === "human" ? UserRound : Bot;
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-md px-1.5 py-0.5 text-xs font-semibold ${toneClasses[tone].soft} ${className}`}>
      <Icon size={12} strokeWidth={2.2} aria-hidden="true" />{agentName(agent)}
    </span>
  );
}

function sameDay(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** A moment in the timeline: "Today, 02:14", "Yesterday, 18:03", or "5 Nov, 14:20". */
export function when(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const time = new Intl.DateTimeFormat(locale(), { hour: "2-digit", minute: "2-digit" }).format(date);
  const now = new Date();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameDay(date, now)) return t("Today, {time}", { time });
  if (sameDay(date, yesterday)) return t("Yesterday, {time}", { time });
  const day = new Intl.DateTimeFormat(locale(), { day: "numeric", month: "short", ...(date.getFullYear() !== now.getFullYear() ? { year: "numeric" } : {}) }).format(date);
  return t("{day}, {time}", { day, time });
}

/** The full date and time, for a tooltip. */
export function exactly(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat(locale(), { dateStyle: "full", timeStyle: "short" }).format(date);
}

/** Loads a review file (a screenshot, an attachment) as an object URL, released when it leaves the screen. */
export function useReviewFileUrl(projectId: string, fileId: string | null): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!fileId) return;
    const controller = new AbortController();
    let made: string | null = null;
    reviewsApi.blob(projectId, fileId, controller.signal).then((blob) => { made = URL.createObjectURL(blob); setUrl(made); }).catch(() => setUrl(null));
    return () => { controller.abort(); if (made) URL.revokeObjectURL(made); };
  }, [projectId, fileId]);
  return url;
}

/** Quotes a line of the review into the comment box. */
export type Quote = (text: string) => void;

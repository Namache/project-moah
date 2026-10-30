import { BadgeCheck, Bug, Circle, CircleCheck, CircleDashed, CircleDot, CircleEllipsis, CirclePause, Database, Lightbulb, Scale, StickyNote, TriangleAlert, type LucideIcon } from "lucide-react";
import type { Tone } from "../components/ui";
import type { MemoryType } from "../types/memory";
import type { TaskStatus } from "../types/task";
import { labels, msg } from "./i18n";

/** One colour and one icon per task status, used by the board, lists, Home and the palette (docs/DESIGN.md). */
export const taskStatusStyle: Record<TaskStatus, { tone: Tone; icon: LucideIcon }> = {
  backlog: { tone: "neutral", icon: CircleDashed },
  todo: { tone: "info", icon: Circle },
  in_progress: { tone: "warning", icon: CircleDot },
  blocked: { tone: "danger", icon: CirclePause },
  review: { tone: "special", icon: CircleEllipsis },
  completed: { tone: "success", icon: CircleCheck },
  archived: { tone: "neutral", icon: CircleDashed },
};

/** One colour, icon and short meaning per memory type. */
export const memoryTypeStyle: Record<MemoryType, { tone: Tone; icon: LucideIcon; meaning: string }> = {
  decision: labels({ tone: "success", icon: BadgeCheck, meaning: msg("Chosen") }, ["meaning"]),
  rule: labels({ tone: "special", icon: Scale, meaning: msg("Follow consistently") }, ["meaning"]),
  fact: labels({ tone: "info", icon: Database, meaning: msg("Established") }, ["meaning"]),
  idea: labels({ tone: "warning", icon: Lightbulb, meaning: msg("Considering, not a requirement") }, ["meaning"]),
  bug: labels({ tone: "danger", icon: Bug, meaning: msg("Tracked problem") }, ["meaning"]),
  note: labels({ tone: "neutral", icon: StickyNote, meaning: msg("For reference") }, ["meaning"]),
  warning: labels({ tone: "warning", icon: TriangleAlert, meaning: msg("Caution") }, ["meaning"]),
};

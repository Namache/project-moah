import { BadgeCheck, Bug, Circle, CircleCheck, CircleDashed, CircleDot, CircleEllipsis, CirclePause, Database, Lightbulb, Scale, StickyNote, TriangleAlert, type LucideIcon } from "lucide-react";
import type { Tone } from "../components/ui";
import type { MemoryType } from "../types/memory";
import type { TaskStatus } from "../types/task";

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
  decision: { tone: "success", icon: BadgeCheck, meaning: "Chosen" },
  rule: { tone: "special", icon: Scale, meaning: "Follow consistently" },
  fact: { tone: "info", icon: Database, meaning: "Established" },
  idea: { tone: "warning", icon: Lightbulb, meaning: "Considering, not a requirement" },
  bug: { tone: "danger", icon: Bug, meaning: "Tracked problem" },
  note: { tone: "neutral", icon: StickyNote, meaning: "For reference" },
  warning: { tone: "warning", icon: TriangleAlert, meaning: "Caution" },
};

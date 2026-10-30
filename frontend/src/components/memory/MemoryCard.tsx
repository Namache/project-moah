import { BookOpenText, Flag, LockKeyhole, Pin } from "lucide-react";
import { Badge, formatDate, toneClasses } from "../ui";
import { memoryTypeStyle } from "../../lib/tones";
import type { MemoryRecord, MemoryType } from "../../types/memory";
import { memoryTypes, visibilityLabels } from "../../types/memory";

function MemoryTypeBadge({ type, showMeaning = false }: { type: MemoryType; showMeaning?: boolean }) {
  const { tone, icon, meaning } = memoryTypeStyle[type];
  const label = memoryTypes.find((item) => item.value === type)?.label ?? type;
  return <Badge tone={tone} icon={icon}>{label}{showMeaning && <span className="font-normal">· {meaning}</span>}</Badge>;
}

const importanceLabels = { critical: "Critical", high: "High importance" } as const;

export function MemoryCard({ memory, selected, onOpen, onTag }: { memory: MemoryRecord; selected: boolean; onOpen: (memory: MemoryRecord) => void; onTag: (tag: string) => void }) {
  const style = memoryTypeStyle[memory.type];
  const typeLabel = memoryTypes.find((item) => item.value === memory.type)?.label ?? memory.type;
  return (
    <li className={`relative flex min-w-0 flex-col overflow-hidden rounded-xl border bg-surface shadow-card transition-shadow hover:shadow-card-hover ${memory.type === "idea" ? "border-dashed border-warning/60" : "border-line"} ${selected ? "ring-2 ring-forest ring-offset-2 ring-offset-canvas" : ""}`}>
      <span className={`absolute inset-x-0 top-0 h-1 ${toneClasses[style.tone].dot}`} aria-hidden="true" />
      <button type="button" aria-pressed={selected} aria-label={`Open ${memory.human_id}: ${memory.title} — ${typeLabel}, ${style.meaning}`} onClick={() => onOpen(memory)} className="flex min-h-36 w-full flex-1 flex-col p-4 pt-5 text-left focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-forest">
        <span className="flex w-full flex-wrap items-center gap-2">
          <MemoryTypeBadge type={memory.type} showMeaning />
          <span className="ml-auto text-xs font-medium tabular-nums text-ink-subtle">{memory.human_id}</span>
        </span>
        <span className="mt-2.5 block w-full text-base font-semibold leading-snug text-ink">{memory.title}</span>
        {memory.content && <span className="mt-2 line-clamp-3 w-full whitespace-pre-line text-sm leading-6 text-ink-muted">{memory.content}</span>}
        {memory.type === "bug" && !memory.is_resolved && memory.pending_note && <span className="mt-3 block w-full rounded-lg bg-warning-soft/80 px-3 py-2 text-xs leading-5 text-warning-ink"><strong>Still pending:</strong> {memory.pending_note}</span>}
        <span className="mt-auto flex w-full flex-wrap items-center gap-x-3 gap-y-1.5 pt-4 text-xs text-ink-muted">
          {memory.type === "bug" && <Badge tone={memory.is_resolved ? "success" : "neutral"}>{memory.is_resolved ? "Resolved" : "Pending"}</Badge>}
          {memory.status !== "active" && <Badge className="capitalize">{memory.status}</Badge>}
          {(memory.importance === "critical" || memory.importance === "high") && <span className="inline-flex items-center gap-1 font-semibold text-warning-ink"><Flag size={12} aria-hidden="true" />{importanceLabels[memory.importance]}</span>}
          {memory.is_pinned && <span className="inline-flex items-center gap-1"><Pin size={12} aria-hidden="true" />Pinned</span>}
          {memory.is_locked && <span className="inline-flex items-center gap-1"><LockKeyhole size={12} aria-hidden="true" />Locked</span>}
          {memory.ai_visibility !== "relevant_only" && <span className="inline-flex items-center gap-1"><BookOpenText size={12} aria-hidden="true" />AI: {visibilityLabels[memory.ai_visibility]}</span>}
          <span className="ml-auto">Updated {formatDate(memory.updated_at)}</span>
        </span>
      </button>
      {memory.tags.length > 0 && <div className="flex flex-wrap gap-1.5 border-t border-line px-4 py-2" aria-label={`${memory.human_id} tags`}>
        {memory.tags.map((tag) => <button key={tag} type="button" onClick={() => onTag(tag)} aria-label={`Filter memory by tag ${tag}`} className="rounded-md bg-hover px-2 py-0.5 text-xs font-medium text-ink-muted hover:text-forest focus-visible:outline-2 focus-visible:outline-forest">#{tag}</button>)}
      </div>}
    </li>
  );
}

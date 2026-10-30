import { useEffect, useState } from "react";
import { Check, Flag, Link2Off, Pencil, Target } from "lucide-react";
import { useTimeout } from "../../hooks/useTimeout";
import type { TaskPriority, TaskStatus, TaskSummary } from "../../types/task";
import { priorityLabels, statusLabels } from "../../types/task";
import { taskStatusStyle } from "../../lib/tones";
import { Badge } from "../ui";

/** A task's status as a coloured label with its icon, the same everywhere a task is listed. */
export function TaskStatusBadge({ status }: { status: TaskStatus }) {
  const { tone, icon } = taskStatusStyle[status];
  return <Badge tone={tone} icon={icon}>{statusLabels[status]}</Badge>;
}

const priorityStyle: Record<TaskPriority, string> = {
  low: "bg-neutral-soft text-neutral-ink",
  normal: "bg-info-soft text-info-ink",
  high: "bg-warning-soft text-warning-ink",
  critical: "bg-danger-soft text-danger-ink",
};

function PriorityBadge({ priority }: { priority: TaskPriority }) {
  // The text label means priority never relies on color alone.
  return <span className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium ${priorityStyle[priority]}`}><Flag size={11} aria-hidden="true" />{priorityLabels[priority]}</span>;
}

export function Progress({ done, total, label }: { done: number; total: number; label: string }) {
  if (total === 0) return null;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-ink-muted" title={label}>
      <span className="h-1.5 w-12 overflow-hidden rounded-full bg-neutral-soft" aria-hidden="true"><span className="block h-full rounded-full bg-primary" style={{ width: `${Math.round((done / total) * 100)}%` }} /></span>
      {done} / {total}
    </span>
  );
}

export function TaskMeta({ task }: { task: TaskSummary }) {
  return (
    <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
      {task.priority !== "normal" && <PriorityBadge priority={task.priority} />}
      <Progress done={task.criteria_completed} total={task.criteria_total} label={`${task.criteria_completed} of ${task.criteria_total} requirements complete`} />
      {task.is_blocked_by_open_dependency && <span className="inline-flex items-center gap-1 text-xs font-semibold text-warning-ink"><Link2Off size={13} aria-hidden="true" />Waiting on a dependency</span>}
      {task.tags.map((tag) => <span key={tag} className="rounded border border-line border-l-2 border-l-forest px-1.5 py-px text-xs font-medium text-ink-muted">{tag}</span>)}
    </div>
  );
}

export function FocusMark({ compact = false }: { compact?: boolean }) {
  if (compact) return <span title="Current focus" className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary text-white"><Target size={12} aria-hidden="true" /><span className="sr-only">Focus</span></span>;
  return <span className="inline-flex items-center gap-1 rounded-full bg-primary px-2 py-0.5 text-xs font-semibold text-white"><Target size={12} aria-hidden="true" />Focus</span>;
}

/**
 * A text field that saves on blur or Enter, and only when the value changed. A required field puts back its value when cleared.
 * A pencil marks it as editable on hover; when onSave returns a promise, the field briefly says "Saved", or shows why it was not.
 */
export function InlineText({ value, onSave, label, multiline = false, placeholder, className = "", readOnly = false, required = false }: { value: string; onSave: (value: string) => void | Promise<unknown>; label: string; multiline?: boolean; placeholder?: string; className?: string; readOnly?: boolean; required?: boolean }) {
  const [draft, setDraft] = useState(value);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [saveError, setSaveError] = useState("");
  const later = useTimeout();
  useEffect(() => setDraft(value), [value]);
  function commit() {
    if (readOnly) return;
    const next = draft.trim();
    if (next === value.trim() || (required && !next)) { setDraft(value); return; }
    const result = onSave(next);
    if (!result) return;
    setSaveState("saving");
    result.then(
      () => { setSaveState("saved"); later(() => setSaveState((state) => (state === "saved" ? "idle" : state)), 2000); },
      (error: unknown) => { setSaveState("error"); setSaveError(error instanceof Error ? error.message : "Please try again."); },
    );
  }
  const shared = {
    "aria-label": label,
    "aria-required": required || undefined,
    "aria-invalid": saveState === "error" || undefined,
    placeholder,
    value: draft,
    readOnly,
    onChange: (event: { target: { value: string } }) => setDraft(event.target.value),
    onBlur: commit,
    className: `inline-field ${readOnly ? "" : "pr-7"} ${className}`,
  };
  return (
    <div className="group/inline relative min-w-0 flex-1">
      {multiline
        ? <textarea {...shared} rows={Math.max(3, draft.split("\n").length)} />
        : <input {...shared} onKeyDown={(event) => { if (event.key === "Enter") (event.target as HTMLInputElement).blur(); if (event.key === "Escape") { setDraft(value); (event.target as HTMLInputElement).blur(); } }} />}
      {!readOnly && saveState !== "saved" && saveState !== "saving" && <Pencil size={13} aria-hidden="true" className={`pointer-events-none absolute right-2 text-ink-subtle opacity-0 transition-opacity group-hover/inline:opacity-100 group-focus-within/inline:opacity-0 ${multiline ? "top-2.5" : "top-1/2 -translate-y-1/2"}`} />}
      {(saveState === "saved" || saveState === "saving") && <span className={`pointer-events-none absolute right-1.5 inline-flex items-center gap-1 rounded bg-surface/90 px-1 text-xs font-medium ${saveState === "saved" ? "text-forest" : "text-ink-subtle"} ${multiline ? "top-2" : "top-1/2 -translate-y-1/2"}`}>
        {saveState === "saved" ? <><Check size={13} aria-hidden="true" />Saved</> : "Saving…"}
      </span>}
      <span role="status" className="sr-only">{saveState === "saved" ? `${label} saved` : ""}</span>
      {saveState === "error" && <p role="alert" className="mt-1 text-xs text-danger-ink">{label} was not saved. {saveError}</p>}
    </div>
  );
}

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Archive, LockKeyhole, Plus, RotateCcw, Trash2, X } from "lucide-react";
import { Button, HelpTip, formatDate } from "../ui";
import { ImageAttachments } from "../images/ImageAttachments";
import { useMemoryActions, useMemoryHistory, useMemoryRecord } from "../../hooks/useMemory";
import { useTask, useTasks } from "../../hooks/useTasks";
import { ConnectedMemories } from "./ConnectedMemories";
import { TypedLinks } from "../links/TypedLinks";
import { memoryTypes, visibilityLabels, type AiVisibility, type MemoryChanges, type MemoryImportance, type MemoryRecord, type MemoryReplacement, type MemoryType } from "../../types/memory";
import type { TaskRef, TaskSummary } from "../../types/task";
import { useModalDialog } from "../../hooks/useModalDialog";
import { labels, msg, t, tx } from "../../lib/i18n";

const importanceLabels: Record<MemoryImportance, string> = labels({ low: msg("Low"), normal: msg("Normal"), high: msg("High"), critical: msg("Critical") });
const statusLabels = labels({ active: msg("Active"), superseded: msg("Superseded"), invalidated: msg("Invalidated"), archived: msg("Archived") });
const typeHelp: Record<MemoryType, string> = labels({
  decision: msg("A choice the project has made."),
  rule: msg("A convention the project should keep following."),
  fact: msg("Something established about the project."),
  idea: msg("Something to consider, not a requirement yet."),
  bug: msg("Incorrect behavior that is known but not yet resolved."),
  note: msg("Useful context without a stronger category."),
  warning: msg("A caution likely to affect future work."),
});
const visibilityHelp: Record<AiVisibility, string> = labels({
  always: msg("Include in future AI context whenever this project is used."),
  relevant_only: msg("Include when relevant to the current work."),
  manual_only: msg("Include only when someone explicitly selects it."),
  hidden: msg("Keep out of AI context. It remains visible to you here."),
});

interface Draft {
  type: MemoryType;
  title: string;
  content: string;
  importance: MemoryImportance;
  ai_visibility: AiVisibility;
  is_pinned: boolean;
  is_locked: boolean;
  is_resolved: boolean;
  tags: string;
  task_ids: string[];
}

function emptyDraft(defaultTaskRef?: string | null, defaultType: MemoryType = "note"): Draft {
  return { type: defaultType, title: "", content: "", importance: "normal", ai_visibility: "relevant_only", is_pinned: false, is_locked: false, is_resolved: false, tags: "", task_ids: defaultTaskRef ? [defaultTaskRef] : [] };
}

function draftFrom(memory: MemoryRecord): Draft {
  return { type: memory.type, title: memory.title, content: memory.content, importance: memory.importance, ai_visibility: memory.ai_visibility, is_pinned: memory.is_pinned, is_locked: memory.is_locked, is_resolved: memory.is_resolved, tags: memory.tags.join(", "), task_ids: memory.tasks.map((task) => task.id) };
}

function splitTags(value: string): string[] {
  return [...new Set(value.split(",").map((tag) => tag.trim()).filter(Boolean))];
}

function selectedTask(task: TaskSummary | TaskRef, refs: string[]): boolean {
  return refs.includes(task.id) || refs.includes(task.human_id);
}

function changesFrom(draft: Draft, memory: MemoryRecord): MemoryChanges {
  const changes: MemoryChanges = {};
  const keepsHistoricalText = memory.status === "superseded" || memory.status === "invalidated";
  if (!keepsHistoricalText && draft.title.trim() !== memory.title) changes.title = draft.title.trim();
  if (!keepsHistoricalText && draft.content.trim() !== memory.content) changes.content = draft.content.trim();
  if (!keepsHistoricalText && draft.importance !== memory.importance) changes.importance = draft.importance;
  if (!keepsHistoricalText && draft.ai_visibility !== memory.ai_visibility) changes.ai_visibility = draft.ai_visibility;
  if (draft.is_pinned !== memory.is_pinned) changes.is_pinned = draft.is_pinned;
  if (draft.is_locked !== memory.is_locked) changes.is_locked = draft.is_locked;
  if (memory.type === "bug" && draft.is_resolved !== memory.is_resolved) changes.is_resolved = draft.is_resolved;
  const tags = splitTags(draft.tags);
  if (!keepsHistoricalText && tags.join("\0") !== memory.tags.join("\0")) changes.tags = tags;
  const taskIds = [...draft.task_ids].sort();
  if (taskIds.join("\0") !== memory.tasks.map((task) => task.id).sort().join("\0")) changes.task_ids = draft.task_ids;
  return changes;
}

type PendingAction = "archive" | "invalidate" | "delete" | null;

export function MemoryPanel({ projectId, memoryRef, onClose, onChanged, readonly, defaultTaskRef, defaultType }: {
  projectId: string;
  memoryRef: string | null;
  onClose: () => void;
  onChanged: (ref: string | null) => void;
  readonly: boolean;
  defaultTaskRef?: string | null;
  /** The type a new record starts as, such as a rule written from a Brain health notice. */
  defaultType?: MemoryType;
}) {
  const creating = memoryRef === null;
  // A new memory opens beside the page, not over it: only Cancel, Add memory or the close button end it.
  const dialogRef = useModalDialog(!creating);
  const loadedId = useRef<string | null>(null);
  const recordQuery = useMemoryRecord(projectId, memoryRef);
  const historyQuery = useMemoryHistory(projectId, memoryRef, !creating);
  const tasksQuery = useTasks(projectId);
  const initialTaskQuery = useTask(projectId, creating ? defaultTaskRef ?? null : null);
  const actions = useMemoryActions(projectId);
  const [draft, setDraft] = useState<Draft>(() => emptyDraft(defaultTaskRef, defaultType));
  const [taskToAdd, setTaskToAdd] = useState("");
  const [pendingAction, setPendingAction] = useState<PendingAction>(null);
  const [replacing, setReplacing] = useState(false);
  const [replacement, setReplacement] = useState<MemoryReplacement>({ title: "", content: "" });
  const [error, setError] = useState("");
  const memory = recordQuery.data;
  const frozenText = memory?.status === "superseded" || memory?.status === "invalidated";
  const busy = Object.values(actions).some((action) => action.isPending);
  const editChanges = memory ? changesFrom(draft, memory) : {};
  const canSave = creating || Object.keys(editChanges).length > 0;


  useEffect(() => {
    if (memory && loadedId.current !== memory.id) {
      setDraft(draftFrom(memory));
      loadedId.current = memory.id;
    }
  }, [memory]);

  function setField<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
    setError("");
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (readonly || busy || !draft.title.trim()) return;
    setError("");
    try {
      if (creating) {
        const saved = await actions.create.mutateAsync({
          type: draft.type, title: draft.title.trim(), content: draft.content.trim(), importance: draft.importance,
          ai_visibility: draft.ai_visibility, is_pinned: draft.is_pinned, is_locked: draft.is_locked,
          is_resolved: draft.type === "bug" ? draft.is_resolved : undefined,
          tags: splitTags(draft.tags), task_ids: draft.task_ids,
        });
        onChanged(saved.human_id);
      } else if (memory && canSave) {
        const saved = await actions.update.mutateAsync({ ref: memory.id, changes: editChanges });
        onChanged(saved.human_id);
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : t("The memory could not be saved.")); }
  }

  async function changeStatus(action: Exclude<PendingAction, null> | "restore") {
    if (!memory || readonly || busy) return;
    setError("");
    try {
      if (action === "delete") {
        await actions.remove.mutateAsync(memory.id);
        onChanged(null);
        onClose();
      } else {
        const changed = await actions[action].mutateAsync(memory.id);
        setPendingAction(null);
        onChanged(changed.human_id);
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : ({ archive: t("The memory could not be archived."), invalidate: t("The memory could not be marked incorrect."), delete: t("The memory could not be deleted."), restore: t("The memory could not be restored.") } as Record<string, string>)[action]); }
  }

  async function supersede(event: FormEvent) {
    event.preventDefault();
    if (!memory || readonly || busy || !replacement.title.trim()) return;
    setError("");
    try {
      const changed = await actions.supersede.mutateAsync({ ref: memory.id, input: { ...replacement, title: replacement.title.trim(), content: replacement.content?.trim() ?? "" } });
      setReplacing(false);
      onChanged(changed.human_id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : t("The replacement could not be created.")); }
  }

  const taskChoices = [...new Map([...(tasksQuery.data ?? []), ...(initialTaskQuery.data ? [initialTaskQuery.data] : []), ...(memory?.tasks ?? [])].map((task) => [task.id, task])).values()];
  const remainingTasks = taskChoices.filter((task) => !selectedTask(task, draft.task_ids));
  const linkedTasks = draft.task_ids.map((ref) => taskChoices.find((task) => task.id === ref || task.human_id === ref) ?? { id: ref, human_id: ref, title: t("Task not loaded"), status: "archived" as const });
  const hasHistory = Boolean(memory?.supersedes_id || memory?.superseded_by);

  return (
    <dialog ref={dialogRef} aria-labelledby="memory-panel-title" onCancel={(event) => { event.preventDefault(); if (!creating) onClose(); }} onClick={(event) => { if (!creating && event.target === dialogRef.current) onClose(); }}
      className="dialog-panel panel-right fixed inset-y-0 right-0 left-auto z-40 m-0 h-full max-h-none w-full max-w-[590px] overflow-y-auto border-l border-line bg-surface p-0 text-ink shadow-dialog backdrop:bg-black/40">
      <div className="flex items-start justify-between gap-3 border-b border-line px-6 py-5">
        <div>
          <p className="text-xs font-bold uppercase tracking-wide text-forest">{memory?.human_id ?? (creating ? t("New memory") : memoryRef)}</p>
          <h2 id="memory-panel-title" className="mt-1 text-xl font-semibold tracking-tight">{creating ? (projectId === "global" ? t("Add global memory") : t("Add project memory")) : memory?.title ?? t("Memory details")}</h2>
          {memory && <p className="mt-1 text-xs text-ink-muted">{t("{status} · Updated {date}", { status: statusLabels[memory.status], date: formatDate(memory.updated_at) })}</p>}
        </div>
        <Button variant="quiet" size="icon" onClick={onClose} aria-label={t("Close memory")}><X size={18} /></Button>
      </div>

      {!creating && recordQuery.isPending && <p role="status" className="px-6 py-10 text-sm text-ink-muted">{t("Loading memory…")}</p>}
      {!creating && recordQuery.isError && <div role="alert" className="m-6 rounded-xl border border-danger/40 bg-danger-soft p-4 text-sm text-danger-ink">{recordQuery.error.message} <Button onClick={() => void recordQuery.refetch()}>{t("Try again")}</Button></div>}
      {error && <p role="alert" className="mx-6 mt-4 rounded-xl border border-danger/40 bg-danger-soft p-3 text-sm text-danger-ink">{error}</p>}

      {(creating || memory) && (
        <>
          {memory?.is_locked && <div className="mx-6 mt-5 rounded-xl border border-warning/40 bg-warning-soft p-4 text-sm text-warning-ink"><LockKeyhole className="mr-2 inline-block align-text-bottom" size={17} aria-hidden="true" />{t("This memory is locked. AI agents cannot change it without your review. Saving changes here is a human action.")}</div>}
          {frozenText && <p className="mx-6 mt-5 rounded-xl bg-neutral-soft p-4 text-sm text-ink-muted">{memory?.status === "superseded" ? t("This memory was replaced. Its text is kept as history and cannot be edited.") : t("This memory is {status}. Its text is kept as history and cannot be edited.", { status: memory ? statusLabels[memory.status].toLowerCase() : "" })}</p>}
          {readonly && <p className="mx-6 mt-5 rounded-xl bg-neutral-soft p-4 text-sm text-ink-muted">{t("Restore this project before changing its memory.")}</p>}

          <form onSubmit={(event) => void save(event)} className="px-6 py-5">
            <div className="space-y-5">
              <div>
                <span className="flex items-center gap-1.5"><label htmlFor="memory-type" className="field-label">{t("Type")}</label><HelpTip label={t("memory types")}>{tx("<b>Decision</b>: something you have chosen, like \"Maximum party size is 4\". <b>Rule</b>: a convention agents should follow. <b>Fact</b>: established information. <b>Idea</b>: something you are considering. Ideas are not requirements. <b>Known issue</b>: incorrect behavior you know about.", { b: (text) => <strong>{text}</strong> })}</HelpTip></span>
                {creating ? <select id="memory-type" className="field-input" value={draft.type} onChange={(event) => setField("type", event.target.value as MemoryType)} disabled={readonly}>{memoryTypes.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}</select>
                  : <p id="memory-type" className="mt-1 text-sm font-semibold text-ink">{memoryTypes.find((type) => type.value === memory?.type)?.label}</p>}
                <p className="mt-1 text-xs text-ink-subtle">{typeHelp[draft.type]} {t("The type cannot change after creation.")}</p>
              </div>
              <div><label htmlFor="memory-title" className="field-label">{t("Title")} <span aria-hidden="true">*</span></label><input id="memory-title" className="field-input" value={draft.title} onChange={(event) => setField("title", event.target.value)} maxLength={200} required disabled={readonly || frozenText} placeholder={t("Maximum party size is 4")} /></div>
              <div><label htmlFor="memory-content" className="field-label">{t("Details")}</label><textarea id="memory-content" className="field-input" rows={6} maxLength={20000} value={draft.content} onChange={(event) => setField("content", event.target.value)} disabled={readonly || frozenText} placeholder={t("Explain what future work should know.")} /></div>
              <div className="grid grid-cols-2 gap-3">
                <div><label htmlFor="memory-importance" className="field-label">{t("Importance")}</label><select id="memory-importance" className="field-input" value={draft.importance} onChange={(event) => setField("importance", event.target.value as MemoryImportance)} disabled={readonly || frozenText}>{(Object.keys(importanceLabels) as MemoryImportance[]).map((value) => <option key={value} value={value}>{importanceLabels[value]}</option>)}</select></div>
                <div><span className="flex items-center gap-1.5"><label htmlFor="memory-visibility" className="field-label">{t("AI visibility")}</label><HelpTip label={t("AI visibility")}>{tx("<b>Always</b>: available whenever relevant project context is built. <b>Relevant only</b>: included when related to the current task. <b>Manual only</b>: included only when you explicitly select it. <b>Hidden</b>: never sent through Project Moah to coding agents.", { b: (text) => <strong>{text}</strong> })}</HelpTip></span><select id="memory-visibility" aria-describedby="memory-visibility-help" className="field-input" value={draft.ai_visibility} onChange={(event) => setField("ai_visibility", event.target.value as AiVisibility)} disabled={readonly || frozenText}>{(Object.keys(visibilityLabels) as AiVisibility[]).map((value) => <option key={value} value={value}>{visibilityLabels[value]}</option>)}</select></div>
              </div>
              <p id="memory-visibility-help" className="-mt-3 text-xs text-ink-subtle">{visibilityHelp[draft.ai_visibility]}</p>
              <div className="flex flex-wrap gap-x-7 gap-y-3">
                {draft.type === "bug" && <label className="flex items-center gap-2 text-sm text-ink"><input type="checkbox" checked={draft.is_resolved} onChange={(event) => setField("is_resolved", event.target.checked)} disabled={readonly} className="h-4 w-4 accent-primary" />{t("Resolved")}</label>}
                <label className="flex items-center gap-2 text-sm text-ink"><input type="checkbox" checked={draft.is_pinned} onChange={(event) => setField("is_pinned", event.target.checked)} disabled={readonly} className="h-4 w-4 accent-primary" />{t("Pin to the top")}</label>
                <span className="flex items-center gap-2"><label className="flex items-center gap-2 text-sm text-ink"><input type="checkbox" aria-describedby="memory-lock-help" checked={draft.is_locked} onChange={(event) => setField("is_locked", event.target.checked)} disabled={readonly} className="h-4 w-4 accent-primary" />{t("Lock memory")}</label><HelpTip label={t("locked memory")}>{t("Locked memory cannot be silently changed by an AI agent. If an agent proposes a change, Project Moah asks you to review it first.")}</HelpTip></span>
              </div>
              <p id="memory-lock-help" className="-mt-3 text-xs text-ink-subtle">{t("Locking protects the memory from AI agent edits. You can still edit, replace, or unlock it yourself.")}</p>
              <div><label htmlFor="memory-tags" className="field-label">{t("Tags")}</label><input id="memory-tags" className="field-input" value={draft.tags} onChange={(event) => setField("tags", event.target.value)} disabled={readonly || frozenText} placeholder={t("gameplay, design (comma separated)")} /></div>
              <div>
                <label htmlFor="memory-task-picker" className="field-label">{t("Linked tasks")}</label>
                {linkedTasks.length > 0 ? <ul className="mt-2 space-y-1.5">{linkedTasks.map((task) => <li key={task.id} className="flex items-center justify-between gap-2 rounded-lg bg-neutral-soft px-3 py-2 text-sm"><span><strong>{task.human_id}</strong> {task.title}</span><button type="button" aria-label={t("Unlink task {id}", { id: task.human_id })} onClick={() => setField("task_ids", draft.task_ids.filter((ref) => ref !== task.id && ref !== task.human_id))} disabled={readonly} className="rounded-md p-1 text-ink-muted hover:bg-neutral-soft disabled:opacity-50"><X size={15} /></button></li>)}</ul> : <p className="mt-1 text-xs text-ink-subtle">{t("No tasks linked yet.")}</p>}
                <div className="mt-2 flex gap-2"><select id="memory-task-picker" className="field-input" value={taskToAdd} onChange={(event) => setTaskToAdd(event.target.value)} disabled={readonly || tasksQuery.isPending || remainingTasks.length === 0}><option value="">{t("Choose a project task…")}</option>{remainingTasks.map((task) => <option key={task.id} value={task.id}>{task.human_id} {task.title}</option>)}</select><Button onClick={() => { if (taskToAdd) { setField("task_ids", [...draft.task_ids, taskToAdd]); setTaskToAdd(""); } }} disabled={readonly || !taskToAdd}><Plus size={16} />{t("Link")}</Button></div>
                {tasksQuery.isError && <p role="alert" className="mt-2 text-xs text-danger-ink">{t("Tasks could not be loaded: {reason}", { reason: tasksQuery.error.message })}</p>}
                {initialTaskQuery.isError && <p role="alert" className="mt-2 text-xs text-danger-ink">{t("The linked task could not be loaded: {reason}", { reason: initialTaskQuery.error.message })}</p>}
              </div>
              {memory && <section className="rounded-xl bg-neutral-soft p-3 text-xs text-ink-muted" aria-label={t("Source details")}><h3 className="font-semibold text-ink">{t("Source")}</h3><p className="mt-1">{memory.source_type || t("Unspecified")}{memory.source_reference ? ` · ${memory.source_reference}` : ""}</p><p>{t("Confidence: {value}", { value: memory.confidence === null ? t("Not recorded") : `${Math.round(memory.confidence * 100)}%` })}</p></section>}
            </div>
            {!readonly && !frozenText && <div className="mt-6 flex justify-end gap-2">{creating && <Button variant="quiet" onClick={onClose} disabled={busy}>{t("Cancel")}</Button>}<Button variant="primary" type="submit" disabled={busy || !draft.title.trim() || !canSave}>{busy ? t("Saving…") : creating ? t("Add memory") : t("Save changes")}</Button></div>}
            {!readonly && frozenText && canSave && <div className="mt-6 flex justify-end"><Button variant="primary" type="submit" disabled={busy}>{busy ? t("Saving…") : t("Save pin, lock, or task links")}</Button></div>}
          </form>

          {memory && <section className="border-t border-line px-6 py-5" aria-labelledby="memory-images-title">
            <h3 id="memory-images-title" className="text-sm font-semibold text-ink">{t("Images")}</h3>
            <p className="mb-3 mt-0.5 text-xs text-ink-subtle">{t("Screenshots or diagrams for this memory. Agents can look at them.")}</p>
            <ImageAttachments projectId={projectId} owner="memory" record={memory.human_id} images={memory.images ?? []} readOnly={readonly} />
          </section>}

          {memory && <section className="border-t border-line px-6 py-5" aria-label={t("Memory history")}>
            <h3 className="text-sm font-semibold text-ink">{t("History")}</h3>
            <p className="mt-1 text-xs text-ink-subtle">{t("Replacement keeps earlier versions for reference.")}</p>
            {historyQuery.isPending && <p role="status" className="mt-3 text-sm text-ink-muted">{t("Loading history…")}</p>}
            {historyQuery.isError && <p role="alert" className="mt-3 text-sm text-danger-ink">{t("History could not be loaded: {reason}", { reason: historyQuery.error.message })} <button type="button" className="underline" onClick={() => void historyQuery.refetch()}>{t("Try again")}</button></p>}
            {historyQuery.data && <ol className="mt-3 space-y-1.5">{historyQuery.data.chain.map((item) => <li key={item.id}><button type="button" onClick={() => onChanged(item.human_id)} aria-current={item.id === memory.id ? "true" : undefined} className="w-full rounded-lg border border-line px-3 py-2 text-left text-sm hover:bg-sage-pale focus-visible:outline-2 focus-visible:outline-forest"><strong className="text-forest">{item.human_id}</strong> {item.title} <span className="text-xs text-ink-subtle">· {statusLabels[item.status]}{item.id === historyQuery.data.current_id ? ` ${t("· Latest")}` : ""}</span></button></li>)}</ol>}
          </section>}

          {memory && <ConnectedMemories projectId={projectId} memory={memory} readonly={readonly || memory.status !== "active"} onOpen={onChanged} />}

          {memory && <section className="border-t border-line px-6 py-5" aria-labelledby="typed-links-title">
            <h3 id="typed-links-title" className="mb-3 flex items-center gap-1.5 text-sm font-semibold text-ink">{t("Links")} <HelpTip label={t("links")}>{t("How this memory relates to tasks, files, other memory and shelves. Agents follow strong links to find what a task needs.")}</HelpTip></h3>
            <TypedLinks projectId={projectId} node={`memory:${memory.id}`} readonly={readonly} onOpen={(node) => { if (node.kind === "memory") onChanged(node.label); }} />
          </section>}

          {memory && !readonly && <section className="border-t border-line px-6 py-5" aria-label={t("Memory actions")}>
            {memory.status === "active" && <div className="flex flex-wrap gap-2"><Button onClick={() => { setReplacing((value) => !value); setPendingAction(null); setReplacement({ title: memory.title, content: memory.content, importance: memory.importance, ai_visibility: memory.ai_visibility, is_locked: memory.is_locked }); }}>{t("Supersede")}</Button><Button variant="quiet" onClick={() => { setPendingAction("archive"); setReplacing(false); }}><Archive size={16} />{t("Archive")}</Button><Button variant="quiet" onClick={() => { setPendingAction("invalidate"); setReplacing(false); }}>{t("Mark incorrect")}</Button></div>}
            {(memory.status === "archived" || memory.status === "invalidated") && <Button onClick={() => void changeStatus("restore")} disabled={busy}><RotateCcw size={16} />{t("Restore memory")}</Button>}
            {replacing && memory.status === "active" && <form onSubmit={(event) => void supersede(event)} className="mt-4 space-y-3 rounded-xl border border-line bg-neutral-soft p-4"><h4 className="font-semibold">{t("Create replacement")}</h4><p className="text-xs text-ink-muted">{t("The old memory is marked replaced. Its text stays in history; the new one inherits its tags and linked tasks.")}</p><div><label htmlFor="replacement-title" className="field-label">{t("New title")}</label><input id="replacement-title" className="field-input" value={replacement.title} onChange={(event) => setReplacement((current) => ({ ...current, title: event.target.value }))} required maxLength={200} /></div><div><label htmlFor="replacement-content" className="field-label">{t("New details")}</label><textarea id="replacement-content" className="field-input" rows={4} maxLength={20000} value={replacement.content ?? ""} onChange={(event) => setReplacement((current) => ({ ...current, content: event.target.value }))} /></div><div className="grid grid-cols-2 gap-3"><div><label htmlFor="replacement-importance" className="field-label">{t("Importance")}</label><select id="replacement-importance" className="field-input" value={replacement.importance ?? memory.importance} onChange={(event) => setReplacement((current) => ({ ...current, importance: event.target.value as MemoryImportance }))}>{(Object.keys(importanceLabels) as MemoryImportance[]).map((value) => <option key={value} value={value}>{importanceLabels[value]}</option>)}</select></div><div><label htmlFor="replacement-visibility" className="field-label">{t("AI visibility")}</label><select id="replacement-visibility" className="field-input" value={replacement.ai_visibility ?? memory.ai_visibility} onChange={(event) => setReplacement((current) => ({ ...current, ai_visibility: event.target.value as AiVisibility }))}>{(Object.keys(visibilityLabels) as AiVisibility[]).map((value) => <option key={value} value={value}>{visibilityLabels[value]}</option>)}</select></div></div><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={replacement.is_locked ?? memory.is_locked} onChange={(event) => setReplacement((current) => ({ ...current, is_locked: event.target.checked }))} className="h-4 w-4 accent-primary" />{t("Lock replacement")}</label>{memory.is_locked && <p className="text-xs text-warning-ink">{t("You are replacing a locked memory as a person. Review the new text before saving.")}</p>}<div className="flex justify-end gap-2"><Button variant="quiet" onClick={() => setReplacing(false)}>{t("Cancel")}</Button><Button variant="primary" type="submit" disabled={!replacement.title.trim() || busy}>{busy ? t("Replacing…") : t("Create replacement")}</Button></div></form>}
            {pendingAction && <div className="mt-4 rounded-xl border border-warning/40 bg-warning-soft p-4 text-sm text-warning-ink"><p className="font-semibold">{pendingAction === "delete" ? t("Delete permanently?") : pendingAction === "invalidate" ? t("Mark this memory incorrect?") : t("Archive this memory?")}</p><p className="mt-1">{pendingAction === "delete" ? t("This removes the record permanently. This cannot be undone.") : pendingAction === "invalidate" ? t("It will leave active memory and remain available in history. You can restore it later.") : t("It will leave active memory. You can restore it later.")}{memory.is_locked && ` ${t("You are approving this change to a locked memory as a person.")}`}</p><div className="mt-3 flex gap-2"><Button variant={pendingAction === "delete" ? "danger" : "primary"} onClick={() => void changeStatus(pendingAction)} disabled={busy}>{pendingAction === "delete" ? t("Delete permanently") : pendingAction === "invalidate" ? t("Mark incorrect") : t("Archive memory")}</Button><Button variant="quiet" onClick={() => setPendingAction(null)}>{t("Cancel")}</Button></div></div>}
            <div className="mt-5 border-t border-line pt-4"><Button variant="quiet" className="text-danger-ink" onClick={() => { setPendingAction("delete"); setReplacing(false); }} disabled={busy || memory.is_locked || hasHistory}><Trash2 size={16} />{t("Delete")}</Button><p className="mt-1 text-xs text-ink-subtle">{memory.is_locked ? t("Unlock and save this memory before deleting it.") : hasHistory ? t("Replacement history cannot be deleted.") : t("Delete is for mistakes. Archive keeps the record and allows restoration.")}</p></div>
          </section>}
        </>
      )}
    </dialog>
  );
}

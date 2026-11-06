import { useEffect, useState, type FormEvent } from "react";
import { Play, Plus, Archive, ArrowDown, ArrowUp, RotateCcw, Trash2, X, Target } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { Button } from "../ui";
import { useCriterionActions, useDeleteTask, useFocus, useMilestones, useRelationshipActions, useStartTask, useTask, useTasks, useUpdateTask } from "../../hooks/useTasks";
import type { RelationshipType, TaskDetail, TaskPriority, TaskStatus } from "../../types/task";
import { boardColumns, priorityLabels } from "../../types/task";
import { HandoffButton } from "../handoff/HandoffButton";
import { WorkOnTaskButton } from "./WorkOnTaskButton";
import { InlineText } from "./TaskBits";
import { LinkedMemory } from "./LinkedMemory";
import { ImageAttachments } from "../images/ImageAttachments";
import { TypedLinks } from "../links/TypedLinks";
import { TaskCheckpoints } from "../checkpoints/CheckpointsSection";
import { useModalDialog } from "../../hooks/useModalDialog";
import { labels, msg, t } from "../../lib/i18n";

const relationshipLabels: Record<string, string> = labels({ depends_on: msg("Depends on"), blocks: msg("Blocks"), parent: msg("Parent"), child: msg("Subtasks"), related_to: msg("Related"), supersedes: msg("Supersedes"), superseded_by: msg("Superseded by") });
const addableRelationships: { value: RelationshipType; label: string }[] = [
  labels({ value: "depends_on", label: msg("Depends on") }, ["label"]), labels({ value: "blocks", label: msg("Blocks") }, ["label"]), labels({ value: "parent", label: msg("Parent is") }, ["label"]), labels({ value: "child", label: msg("Has subtask") }, ["label"]), labels({ value: "related_to", label: msg("Related to") }, ["label"]), labels({ value: "supersedes", label: msg("Supersedes") }, ["label"]), labels({ value: "superseded_by", label: msg("Superseded by") }, ["label"]),
];

function Section({ title, children, hint }: { title: string; children: React.ReactNode; hint?: string }) {
  return <section className="border-t border-line px-6 py-5"><h3 className="text-sm font-semibold text-ink">{title}</h3>{hint && <p className="mt-0.5 text-xs text-ink-subtle">{hint}</p>}<div className="mt-3">{children}</div></section>;
}

function Criteria({ projectId, task, readOnly }: { projectId: string; task: TaskDetail; readOnly: boolean }) {
  const { add, update, remove } = useCriterionActions(projectId, task.id);
  const [draft, setDraft] = useState("");
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!draft.trim()) return;
    add.mutate(draft.trim(), { onSuccess: () => setDraft("") });
  }
  return (
    <>
      <ul className="space-y-1.5">
        {task.acceptance_criteria.map((c, index) => (
          <li key={c.id} className="group flex items-start gap-2.5">
            <input type="checkbox" checked={c.is_completed} disabled={readOnly} onChange={(e) => update.mutate({ id: c.id, changes: { is_completed: e.target.checked } })} aria-label={t("Done: {text}", { text: c.description })} className="mt-2 h-4 w-4 accent-primary" />
            <InlineText value={c.description} label={t("Requirement")} readOnly={readOnly} onSave={(value) => value ? update.mutateAsync({ id: c.id, changes: { description: value } }) : remove.mutate(c.id)} className={c.is_completed ? "text-ink-subtle line-through" : ""} />
            {!readOnly && <div className="flex shrink-0 items-center">
              <button type="button" onClick={() => update.mutate({ id: c.id, changes: { sort_order: index - 1 } })} disabled={index === 0 || update.isPending} aria-label={t("Move requirement up: {text}", { text: c.description })} className="rounded-lg p-1.5 text-ink-subtle hover:bg-sage-pale hover:text-ink focus-visible:outline-2 focus-visible:outline-forest disabled:opacity-35"><ArrowUp size={15} aria-hidden="true" /></button>
              <button type="button" onClick={() => update.mutate({ id: c.id, changes: { sort_order: index + 1 } })} disabled={index === task.acceptance_criteria.length - 1 || update.isPending} aria-label={t("Move requirement down: {text}", { text: c.description })} className="rounded-lg p-1.5 text-ink-subtle hover:bg-sage-pale hover:text-ink focus-visible:outline-2 focus-visible:outline-forest disabled:opacity-35"><ArrowDown size={15} aria-hidden="true" /></button>
            </div>}
            {!readOnly && <button type="button" onClick={() => remove.mutate(c.id)} aria-label={t("Remove requirement: {text}", { text: c.description })} className="mt-1.5 rounded-lg p-1.5 text-ink-subtle opacity-0 hover:bg-sage-pale hover:text-ink focus-visible:opacity-100 group-hover:opacity-100"><X size={15} /></button>}
          </li>
        ))}
      </ul>
      {!readOnly && <form onSubmit={submit} className="mt-2 flex gap-2">
        <input value={draft} onChange={(e) => setDraft(e.target.value)} aria-label={t("Add a requirement")} placeholder={t("Add a requirement")} className="field-input" maxLength={1000} />
        <Button type="submit" disabled={!draft.trim() || add.isPending}><Plus size={16} />{t("Add")}</Button>
      </form>}
      {(add.isError || update.isError || remove.isError) && <p role="alert" className="mt-2 text-sm text-danger-ink">{(add.error ?? update.error ?? remove.error)?.message}</p>}
    </>
  );
}

function Relationships({ projectId, task, readOnly }: { projectId: string; task: TaskDetail; readOnly: boolean }) {
  const { add, remove } = useRelationshipActions(projectId, task.id);
  const { data: all } = useTasks(projectId);
  const [type, setType] = useState<RelationshipType>("depends_on");
  const [target, setTarget] = useState("");
  const linked = new Set(task.relationships.map((r) => r.task.id));
  const [params] = useSearchParams();
  /** Opens a linked task in place, keeping the board's filters. */
  const taskHref = (ref: string) => { const next = new URLSearchParams(params); next.set("task", ref); next.delete("checkpoint"); return `?${next}`; };
  const candidates = (all ?? []).filter((t) => t.id !== task.id && !linked.has(t.id));
  return (
    <>
      {task.relationships.length === 0 && <p className="text-sm text-ink-subtle">{t("No links yet.")}</p>}
      <ul className="space-y-1.5">
        {task.relationships.map((r) => (
          <li key={r.id} className="flex items-center gap-2 text-sm">
            <span className="w-24 shrink-0 text-xs font-semibold text-ink-muted">{relationshipLabels[r.type] ?? r.type}</span>
            <Link to={taskHref(r.task.human_id)} replace className="min-w-0 flex-1 truncate font-medium text-forest hover:underline"><span className="font-bold">{r.task.human_id}</span> {r.task.title}</Link>
            {!readOnly && <button type="button" onClick={() => remove.mutate(r.id)} aria-label={t("Remove link to {id}", { id: r.task.human_id })} className="rounded-lg p-1.5 text-ink-subtle hover:bg-sage-pale"><X size={15} /></button>}
          </li>
        ))}
      </ul>
      {!readOnly && candidates.length > 0 && (
        <form className="mt-3 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (target) add.mutate({ type, target }, { onSuccess: () => setTarget("") }); }}>
          <select aria-label={t("Link type")} value={type} onChange={(e) => setType(e.target.value as RelationshipType)} className="field-input !w-auto">{addableRelationships.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select>
          <select aria-label={t("Linked task")} value={target} onChange={(e) => setTarget(e.target.value)} className="field-input !w-auto min-w-0 flex-1"><option value="">{t("Choose a task…")}</option>{candidates.map((t) => <option key={t.id} value={t.id}>{t.human_id} {t.title}</option>)}</select>
          <Button type="submit" disabled={!target || add.isPending}>{t("Link")}</Button>
        </form>
      )}
      {add.isError && <p role="alert" className="mt-2 text-sm text-danger-ink">{add.error.message}</p>}
    </>
  );
}

export function TaskPanel({ projectId, projectArchived, taskRef, onClose, onChanged }: { projectId: string; projectArchived: boolean; taskRef: string; onClose: () => void; onChanged: (task: TaskDetail | null) => void }) {
  const dialogRef = useModalDialog();
  const remove = useDeleteTask(projectId);
  // While the task is being deleted, stop refreshing it so the closing panel does not ask for a record that is gone.
  const query = useTask(projectId, taskRef, remove.isIdle || remove.isError);
  const update = useUpdateTask(projectId);
  const start = useStartTask(projectId);
  const focus = useFocus(projectId);
  const { data: milestones } = useMilestones(projectId, true);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const task = query.data;

  // After a rename or status change, keep the URL on the task's human ID.
  useEffect(() => { if (task && task.human_id !== taskRef) onChanged(task); }, [task, taskRef, onChanged]);

  const save = (changes: Parameters<typeof update.mutate>[0]["changes"]) => task && update.mutate({ id: task.id, changes });
  /** For inline fields: resolves once saved, so the field can say so. */
  const saveField = (changes: Parameters<typeof update.mutate>[0]["changes"]) => task ? update.mutateAsync({ id: task.id, changes }) : undefined;
  const error = (query.error ?? update.error ?? start.error ?? focus.error ?? remove.error) as Error | null;

  return (
    <dialog ref={dialogRef} aria-label={task ? `${task.human_id} ${task.title}` : t("Task details")} onCancel={(e) => { e.preventDefault(); onClose(); }} onClick={(e) => { if (e.target === dialogRef.current) onClose(); }}
      className="dialog-panel panel-right fixed inset-y-0 right-0 left-auto m-0 h-full max-h-none w-full max-w-[560px] overflow-y-auto border-l border-line bg-surface p-0 text-ink shadow-dialog backdrop:bg-black/40">
      <div className="flex items-center justify-between gap-3 px-6 pb-1 pt-4">
        <span className="text-sm font-bold tracking-wide text-forest">{task?.human_id ?? taskRef}</span>
        <div className="flex items-center gap-1">
          {task && !projectArchived && task.status !== "archived" && <Button variant="quiet" size="icon" onClick={() => save({ status: "archived" })} aria-label={t("Archive")} title={t("Archive: hide from the board but keep the task and its history")}><Archive size={17} aria-hidden="true" /></Button>}
          {task && !projectArchived && !confirmDelete && <Button variant="quiet" size="icon" className="hover:!text-danger-ink" onClick={() => setConfirmDelete(true)} aria-label={t("Delete")} title={t("Delete permanently")}><Trash2 size={17} aria-hidden="true" /></Button>}
          <Button variant="quiet" size="icon" onClick={onClose} aria-label={t("Close task")} title={t("Close")}><X size={18} aria-hidden="true" /></Button>
        </div>
      </div>
      {task && confirmDelete && <div role="group" aria-label={t("Confirm delete")} className="mx-6 mt-2 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-danger/40 bg-danger-soft px-4 py-2.5 text-sm text-danger-ink">
        <span>{t("Delete {id} permanently? Archive keeps its history instead.", { id: task.human_id })}</span>
        <span className="flex gap-2"><Button variant="quiet" size="sm" onClick={() => setConfirmDelete(false)}>{t("Cancel")}</Button><Button variant="danger" size="sm" onClick={() => remove.mutate(task.id, { onSuccess: onClose })} disabled={remove.isPending}>{t("Delete")}</Button></span>
      </div>}
      {query.isPending && <p role="status" className="px-6 py-10 text-sm text-ink-muted">{t("Loading task…")}</p>}
      {error && <div role="alert" className="mx-6 mb-4 rounded-xl border border-danger/40 bg-danger-soft px-4 py-3 text-sm text-danger-ink">{error.message}</div>}
      {projectArchived && <p className="mx-6 mb-4 rounded-xl bg-neutral-soft px-4 py-3 text-sm text-ink-muted">{t("Restore this project to edit its tasks.")}</p>}
      {task && (
        <>
          <div className="px-6 pb-5">
            <InlineText value={task.title} label={t("Title")} required readOnly={projectArchived} onSave={(value) => saveField({ title: value })} className="!text-xl !font-semibold" />
            <div className="mt-3 flex flex-wrap items-start gap-1.5" aria-label={t("Task actions")} role="group">
              {!projectArchived && (task.status === "archived"
                ? <Button variant="primary" onClick={() => save({ status: "todo" })}><RotateCcw size={16} aria-hidden="true" />{t("Restore task")}</Button>
                : task.status === "completed" ? null
                : task.status === "in_progress" && task.is_focus
                  ? <Button onClick={() => focus.mutate(null)} disabled={focus.isPending} title={t("Stop pointing agents at this task")}><Target size={16} aria-hidden="true" />{t("Clear focus")}</Button>
                  : <Button variant="primary" onClick={() => start.mutate(task.id)} disabled={start.isPending} title={t("Mark in progress and make it the project's focus")}><Play size={16} aria-hidden="true" />{task.status === "in_progress" ? t("Continue work") : t("Start work")}</Button>)}
              {task.status !== "archived" && <WorkOnTaskButton projectId={projectId} task={task.human_id} compact variant={task.status === "in_progress" && task.is_focus ? "primary" : "secondary"} />}
              <HandoffButton projectId={projectId} task={task.human_id} variant="quiet" />
            </div>
            <div className="mt-5 grid grid-cols-2 gap-3">
              <label className="text-xs font-semibold text-ink-muted">{t("Status")}
                <select value={task.status} disabled={projectArchived} onChange={(e) => save({ status: e.target.value as TaskStatus })} className="field-input mt-1">{[...boardColumns, { status: "archived" as TaskStatus, label: t("Archived") }].map((c) => <option key={c.status} value={c.status}>{c.label}</option>)}</select></label>
              <label className="text-xs font-semibold text-ink-muted">{t("Priority")}
                <select value={task.priority} disabled={projectArchived} onChange={(e) => save({ priority: e.target.value as TaskPriority })} className="field-input mt-1">{(Object.keys(priorityLabels) as TaskPriority[]).map((p) => <option key={p} value={p}>{priorityLabels[p]}</option>)}</select></label>
              <label className="col-span-2 text-xs font-semibold text-ink-muted">{t("Milestone")}
                <select value={task.milestone_id ?? ""} disabled={projectArchived} onChange={(e) => save({ milestone_id: e.target.value || null })} className="field-input mt-1"><option value="">{t("No milestone")}</option>{milestones?.map((m) => <option key={m.id} value={m.id} disabled={m.status === "archived" && m.id !== task.milestone_id}>{m.name}{m.status === "archived" ? ` ${t("(archived)")}` : ""}</option>)}</select></label>
            </div>
          </div>
          <Section title={t("Description")}><InlineText multiline value={task.description ?? ""} label={t("Description")} readOnly={projectArchived} placeholder={t("Describe what this task is about")} onSave={(value) => saveField({ description: value || null })} /></Section>
          <Section title={t("Images")} hint={t("Screenshots or sketches for this task. Agents can look at them.")}><ImageAttachments projectId={projectId} owner="tasks" record={task.human_id} images={task.images ?? []} readOnly={projectArchived} /></Section>
          <Section title={t("Acceptance criteria")} hint={task.criteria_total ? t("{done} of {count} complete. Agents use these to judge whether the task is done.", { done: task.criteria_completed, count: task.criteria_total }) : t("Add the requirements that mean this task is finished.")}><Criteria projectId={projectId} task={task} readOnly={projectArchived} /></Section>
          <Section title={t("Next action")} hint={t("The single next step a person or agent should take.")}><InlineText value={task.next_action ?? ""} label={t("Next action")} readOnly={projectArchived} placeholder={t("What should happen next?")} onSave={(value) => saveField({ next_action: value || null })} /></Section>
          <Section title={t("Linked tasks")}><Relationships projectId={projectId} task={task} readOnly={projectArchived} /></Section>
          <Section title={t("Linked memory")} hint={t("Active decisions, rules, and other project knowledge connected to this task.")}><LinkedMemory projectId={projectId} task={task} readOnly={projectArchived} /></Section>
          <Section title={t("Links")} hint={t("How this task relates to files, memory, other tasks and shelves. Agents follow strong links to find what this task needs.")}><TypedLinks projectId={projectId} node={`task:${task.id}`} readonly={projectArchived} /></Section>
          <TaskCheckpoints projectId={projectId} taskId={task.id} archived={projectArchived || task.status === "archived"} />
          <Section title={t("Tags")}><InlineText value={task.tags.join(", ")} label={t("Tags")} readOnly={projectArchived} placeholder={t("gameplay, UI (comma separated)")} onSave={(value) => saveField({ tags: value.split(",").map((t) => t.trim()).filter(Boolean) })} /></Section>
        </>
      )}
    </dialog>
  );
}

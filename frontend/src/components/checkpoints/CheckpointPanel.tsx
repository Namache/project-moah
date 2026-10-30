import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { X } from "lucide-react";
import { Button, formatDate } from "../ui";
import { useCheckpoint, useCheckpointActions } from "../../hooks/useCheckpoints";
import { useTasks } from "../../hooks/useTasks";
import type { Checkpoint, CheckpointChanges, CheckpointInput } from "../../types/checkpoint";
import { taskPath } from "../../lib/routes";
import { useModalDialog } from "../../hooks/useModalDialog";
import { labels, msg, t } from "../../lib/i18n";

interface Draft {
  title: string;
  summary: string;
  completed_work: string;
  remaining_work: string;
  problems: string;
  next_steps: string;
  agent: string;
  git_commit: string;
  task_id: string;
}

function emptyDraft(defaultTaskId?: string): Draft {
  return { title: "", summary: "", completed_work: "", remaining_work: "", problems: "", next_steps: "", agent: "", git_commit: "", task_id: defaultTaskId ?? "" };
}

function draftFrom(record: Checkpoint): Draft {
  return {
    title: record.title, summary: record.summary, completed_work: record.completed_work,
    remaining_work: record.remaining_work, problems: record.problems, next_steps: record.next_steps,
    agent: record.agent ?? "", git_commit: record.git_commit ?? "", task_id: record.task_id ?? "",
  };
}

function inputFrom(draft: Draft): CheckpointInput {
  return {
    title: draft.title.trim(), summary: draft.summary.trim(), completed_work: draft.completed_work.trim(),
    remaining_work: draft.remaining_work.trim(), problems: draft.problems.trim(), next_steps: draft.next_steps.trim(),
    agent: draft.agent.trim() || null, git_commit: draft.git_commit.trim() || null, task_id: draft.task_id || null,
  };
}

function changesFrom(draft: Draft, record: Checkpoint): CheckpointChanges {
  const input = inputFrom(draft);
  const changes: CheckpointChanges = {};
  for (const key of ["title", "summary", "completed_work", "remaining_work", "problems", "next_steps", "agent", "git_commit", "task_id"] as const) {
    if (input[key] !== record[key]) Object.assign(changes, { [key]: input[key] });
  }
  return changes;
}

const sections = [
  labels({ key: "summary", label: msg("Summary"), hint: msg("The state of the work at this moment."), rows: 3 }, ["label", "hint"]),
  labels({ key: "completed_work", label: msg("Completed work"), hint: msg("What is finished and verified?"), rows: 4 }, ["label", "hint"]),
  labels({ key: "remaining_work", label: msg("Remaining work"), hint: msg("What is still unfinished?"), rows: 4 }, ["label", "hint"]),
  labels({ key: "problems", label: msg("Problems"), hint: msg("Blockers, failures, and known risks."), rows: 3 }, ["label", "hint"]),
  labels({ key: "next_steps", label: msg("Next steps"), hint: msg("What should the next person or agent do first?"), rows: 4 }, ["label", "hint"]),
] as const;

export function CheckpointPanel({ projectId, checkpointId, defaultTaskId, readonly, onClose, onChanged }: {
  projectId: string;
  checkpointId: string | null;
  defaultTaskId?: string;
  readonly: boolean;
  onClose: () => void;
  onChanged: (id: string) => void;
}) {
  const dialogRef = useModalDialog();
  const creating = checkpointId === null;
  const recordQuery = useCheckpoint(projectId, checkpointId);
  const tasksQuery = useTasks(projectId);
  const actions = useCheckpointActions(projectId);
  const [draft, setDraft] = useState<Draft>(() => emptyDraft(defaultTaskId));
  const [error, setError] = useState("");
  const record = recordQuery.data;
  const wrongTask = Boolean(record && defaultTaskId && record.task_id !== defaultTaskId);
  const changes = record ? changesFrom(draft, record) : {};
  const busy = actions.create.isPending || actions.update.isPending;
  const canSave = Boolean(draft.title.trim()) && (creating || Object.keys(changes).length > 0);


  useEffect(() => {
    if (record) setDraft(draftFrom(record));
  }, [record]);

  function setField<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
    setError("");
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (readonly || wrongTask || busy || !canSave) return;
    setError("");
    try {
      const saved = creating
        ? await actions.create.mutateAsync(inputFrom(draft))
        : await actions.update.mutateAsync({ id: record!.id, changes });
      onChanged(saved.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("The checkpoint could not be saved."));
    }
  }

  const taskOptions = [...(tasksQuery.data ?? [])];
  if (record?.task && !taskOptions.some((task) => task.id === record.task?.id)) {
    taskOptions.push({ ...record.task, project_id: projectId, milestone_id: null, priority: "normal", next_action: null, sort_order: 0, criteria_total: 0, criteria_completed: 0, tags: [], is_focus: false, is_blocked_by_open_dependency: false });
  }

  return (
    <dialog ref={dialogRef} aria-labelledby="checkpoint-panel-title" onCancel={(event) => { event.preventDefault(); onClose(); }} onClick={(event) => { if (event.target === dialogRef.current) onClose(); }}
      className="dialog-panel panel-right fixed inset-y-0 right-0 left-auto m-0 h-full max-h-none w-full max-w-[620px] overflow-y-auto border-l border-line bg-surface p-0 text-ink shadow-dialog backdrop:bg-black/40">
      <div className="flex items-start justify-between gap-3 border-b border-line px-6 py-5">
        <div>
          <p className="text-xs font-bold uppercase tracking-wide text-forest">{creating ? t("New checkpoint") : t("Checkpoint")}</p>
          <h2 id="checkpoint-panel-title" className="mt-1 text-xl font-semibold tracking-tight">{creating ? t("Record progress") : record?.title ?? t("Checkpoint details")}</h2>
          {record && <p className="mt-1 text-xs text-ink-muted">{t("Created {created} · Updated {updated}", { created: formatDate(record.created_at), updated: formatDate(record.updated_at) })}</p>}
        </div>
        <Button variant="quiet" size="icon" onClick={onClose} aria-label={t("Close checkpoint")}><X size={18} /></Button>
      </div>

      {!creating && recordQuery.isPending && <p role="status" className="px-6 py-10 text-sm text-ink-muted">{t("Loading checkpoint…")}</p>}
      {!creating && recordQuery.isError && <div role="alert" className="m-6 rounded-xl border border-danger/40 bg-danger-soft p-4 text-sm text-danger-ink">{recordQuery.error.message} <Button onClick={() => void recordQuery.refetch()}>{t("Try again")}</Button></div>}
      {error && <p role="alert" className="mx-6 mt-4 rounded-xl border border-danger/40 bg-danger-soft p-3 text-sm text-danger-ink">{error}</p>}
      {readonly && <p className="mx-6 mt-4 rounded-xl bg-neutral-soft p-4 text-sm text-ink-muted">{t("Checkpoints are read-only while their project or task is archived.")}</p>}
      {wrongTask && <p role="alert" className="mx-6 mt-4 rounded-xl border border-warning/40 bg-warning-soft p-4 text-sm text-warning-ink">{t("This checkpoint does not belong to the open task. Close it and choose a checkpoint from this task.")}</p>}

      {(creating || record) && !wrongTask && <form onSubmit={(event) => void save(event)} className="space-y-5 px-6 py-6">
        <div><label htmlFor="checkpoint-title" className="field-label">{t("Title")} <span aria-hidden="true">*</span></label><input id="checkpoint-title" className="field-input" value={draft.title} onChange={(event) => setField("title", event.target.value)} maxLength={200} required disabled={readonly} placeholder={t("Capacity work is ready for migration")} /></div>
        {sections.map(({ key, label, hint, rows }) => <div key={key}><label htmlFor={`checkpoint-${key}`} className="field-label">{label}</label><textarea id={`checkpoint-${key}`} className="field-input" rows={rows} maxLength={20000} value={draft[key]} onChange={(event) => setField(key, event.target.value)} disabled={readonly} placeholder={hint} /><p className="mt-1 text-xs text-ink-subtle">{hint}</p></div>)}
        <div>
          <label htmlFor="checkpoint-task" className="field-label">{t("Linked task")}</label>
          {defaultTaskId ? <p id="checkpoint-task" className="mt-1 text-sm text-ink-muted">{t("This checkpoint belongs to the open task.")}</p>
            : <select id="checkpoint-task" className="field-input" value={draft.task_id} onChange={(event) => setField("task_id", event.target.value)} disabled={readonly || tasksQuery.isPending}><option value="">{t("Project-wide checkpoint")}</option>{taskOptions.map((task) => <option key={task.id} value={task.id}>{task.human_id} {task.title}</option>)}</select>}
          {record?.task && <Link className="mt-2 inline-block text-xs font-semibold text-forest hover:underline" to={taskPath(projectId, record.task.human_id)}>{t("Open {id}", { id: record.task.human_id })} · {record.task.title}</Link>}
          {tasksQuery.isError && !defaultTaskId && <p role="alert" className="mt-1 text-xs text-danger-ink">{t("Tasks could not be loaded:")} {tasksQuery.error.message}</p>}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div><label htmlFor="checkpoint-agent" className="field-label">{t("Agent")}</label><input id="checkpoint-agent" className="field-input" value={draft.agent} onChange={(event) => setField("agent", event.target.value)} maxLength={120} disabled={readonly} placeholder={t("Optional")} /></div>
          <div><label htmlFor="checkpoint-commit" className="field-label">{t("Git commit")}</label><input id="checkpoint-commit" className="field-input font-mono text-xs" value={draft.git_commit} onChange={(event) => setField("git_commit", event.target.value)} maxLength={64} disabled={readonly} placeholder={t("Optional hash")} /></div>
        </div>
        {!readonly && <div className="flex justify-end"><Button variant="primary" type="submit" disabled={!canSave || busy}>{busy ? t("Saving…") : creating ? t("Create checkpoint") : t("Save changes")}</Button></div>}
      </form>}
    </dialog>
  );
}

import { useState, type FormEvent } from "react";
import { Archive, ArrowDown, ArrowUp, Pencil, Plus, RotateCcw } from "lucide-react";
import { Button } from "../ui";
import { useMilestoneActions } from "../../hooks/useTasks";
import type { Milestone, MilestoneChanges, MilestoneStatus } from "../../types/task";

const statusLabels: Record<MilestoneStatus, string> = {
  planned: "Planned", active: "Active", completed: "Completed", archived: "Archived",
};

function MilestoneEditor({ projectId, milestone, onDone }: { projectId: string; milestone: Milestone; onDone: () => void }) {
  const { update } = useMilestoneActions(projectId);
  const [name, setName] = useState(milestone.name);
  const [description, setDescription] = useState(milestone.description ?? "");
  const [targetDate, setTargetDate] = useState(milestone.target_date ?? "");
  const [status, setStatus] = useState(milestone.status);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    const changes: MilestoneChanges = {
      name: name.trim(),
      description: description.trim() || null,
      target_date: targetDate || null,
      status,
    };
    try {
      await update.mutateAsync({ id: milestone.id, changes });
      onDone();
    } catch { /* The error is shown beside the form. */ }
  }

  return (
    <form onSubmit={submit} aria-label={`Edit ${milestone.name} milestone`} className="mt-4 space-y-3 border-t border-line pt-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2"><label className="field-label" htmlFor={`milestone-name-${milestone.id}`}>Milestone name</label><input id={`milestone-name-${milestone.id}`} className="field-input" value={name} onChange={(event) => setName(event.target.value)} maxLength={120} required /></div>
        <div className="sm:col-span-2"><label className="field-label" htmlFor={`milestone-description-${milestone.id}`}>Description</label><textarea id={`milestone-description-${milestone.id}`} className="field-input" value={description} onChange={(event) => setDescription(event.target.value)} maxLength={4000} rows={3} placeholder="What does this milestone deliver?" /></div>
        <div><label className="field-label" htmlFor={`milestone-date-${milestone.id}`}>Target date</label><input id={`milestone-date-${milestone.id}`} type="date" className="field-input" value={targetDate} onChange={(event) => setTargetDate(event.target.value)} /></div>
        <div><label className="field-label" htmlFor={`milestone-status-${milestone.id}`}>Status</label><select id={`milestone-status-${milestone.id}`} className="field-input" value={status} onChange={(event) => setStatus(event.target.value as MilestoneStatus)}>{(Object.keys(statusLabels) as MilestoneStatus[]).map((value) => <option key={value} value={value}>{statusLabels[value]}</option>)}</select></div>
      </div>
      {update.isError && <p role="alert" className="text-sm text-danger-ink">{update.error.message}</p>}
      <div className="flex justify-end gap-2"><Button variant="quiet" onClick={onDone}>Cancel</Button><Button variant="primary" type="submit" disabled={update.isPending || !name.trim()}>{update.isPending ? "Saving…" : "Save milestone"}</Button></div>
    </form>
  );
}

export function MilestoneManager({ projectId, milestones, readonly = false }: { projectId: string; milestones: Milestone[]; readonly?: boolean }) {
  const { create, update } = useMilestoneActions(projectId);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  function add(event: FormEvent) {
    event.preventDefault();
    if (draft.trim()) create.mutate(draft.trim(), { onSuccess: () => setDraft("") });
  }

  return (
    <section aria-label="Manage milestones" className="mb-5 rounded-xl border border-line bg-surface p-4 shadow-card sm:p-5">
      <h2 className="text-base font-semibold text-ink">Milestones</h2>
      <p className="mt-1 text-sm text-ink-muted">Set each stage of the project and track its tasks. Archived milestones stay here so you can restore them.</p>
      {!readonly && <form onSubmit={add} className="mt-4 flex gap-2">
        <input aria-label="New milestone name" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="New milestone name, e.g. Demo 0.2" className="field-input !min-h-10" maxLength={120} />
        <Button type="submit" className="shrink-0 whitespace-nowrap" disabled={!draft.trim() || create.isPending}><Plus size={16} aria-hidden="true" />Add milestone</Button>
      </form>}
      {create.isError && <p role="alert" className="mt-2 text-sm text-danger-ink">{create.error.message}</p>}
      {milestones.length === 0 ? <p className="mt-4 text-sm text-ink-muted">No milestones yet.{readonly ? "" : " Name the first stage of the project above."}</p> : (
        <ul className="mt-4 space-y-3">
          {milestones.map((milestone, index) => (
            <li key={milestone.id} className="rounded-xl border border-line bg-neutral-soft/60 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2"><h3 className="font-semibold text-ink">{milestone.name}</h3><span className="rounded-full bg-sage-pale px-2 py-0.5 text-xs font-semibold text-forest">{statusLabels[milestone.status]}</span></div>
                  <p className="mt-1 text-xs text-ink-muted">{milestone.completed_task_count} of {milestone.task_count} tasks complete{milestone.target_date ? ` · Target ${milestone.target_date}` : ""}</p>
                  {milestone.description && <p className="mt-2 whitespace-pre-wrap text-sm text-ink-muted">{milestone.description}</p>}
                </div>
                {!readonly && <div className="flex flex-wrap gap-1">
                  <Button variant="quiet" size="icon" aria-label={`Move ${milestone.name} up`} title="Move up" disabled={index === 0 || update.isPending} onClick={() => update.mutate({ id: milestone.id, changes: { sort_order: index - 1 } })}><ArrowUp size={16} aria-hidden="true" /></Button>
                  <Button variant="quiet" size="icon" aria-label={`Move ${milestone.name} down`} title="Move down" disabled={index === milestones.length - 1 || update.isPending} onClick={() => update.mutate({ id: milestone.id, changes: { sort_order: index + 1 } })}><ArrowDown size={16} aria-hidden="true" /></Button>
                  <Button variant="quiet" size="icon" aria-label={`Edit ${milestone.name}`} title="Edit milestone" onClick={() => setEditingId(editingId === milestone.id ? null : milestone.id)}><Pencil size={16} aria-hidden="true" /></Button>
                  {milestone.status === "archived"
                    ? <Button variant="quiet" size="icon" aria-label={`Restore ${milestone.name}`} title="Restore milestone" disabled={update.isPending} onClick={() => update.mutate({ id: milestone.id, changes: { status: "planned" } })}><RotateCcw size={16} aria-hidden="true" /></Button>
                    : <Button variant="quiet" size="icon" aria-label={`Archive ${milestone.name}`} title="Archive milestone" disabled={update.isPending} onClick={() => update.mutate({ id: milestone.id, changes: { status: "archived" } })}><Archive size={16} aria-hidden="true" /></Button>}
                </div>}
              </div>
              {!readonly && editingId === milestone.id && <MilestoneEditor key={milestone.id} projectId={projectId} milestone={milestone} onDone={() => setEditingId(null)} />}
            </li>
          ))}
        </ul>
      )}
      {update.isError && <p role="alert" className="mt-3 text-sm text-danger-ink">{update.error.message}</p>}
    </section>
  );
}

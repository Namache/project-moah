import { useState, type FormEvent } from "react";
import { X } from "lucide-react";
import { Button } from "../ui";
import { useCreateTask, useMilestones } from "../../hooks/useTasks";
import type { TaskDetail, TaskStatus } from "../../types/task";
import { useModalDialog } from "../../hooks/useModalDialog";
import { t } from "../../lib/i18n";

export function NewTaskDialog({ projectId, defaultStatus = "todo", defaultMilestone = "", onClose, onCreated }: { projectId: string; defaultStatus?: TaskStatus; defaultMilestone?: string; onClose: () => void; onCreated: (task: TaskDetail) => void }) {
  const ref = useModalDialog();
  const create = useCreateTask(projectId);
  const { data: milestones } = useMilestones(projectId);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [milestone, setMilestone] = useState(defaultMilestone);
  const [criteria, setCriteria] = useState("");


  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    try {
      const task = await create.mutateAsync({
        title: title.trim(),
        status: defaultStatus,
        description: description.trim() || null,
        milestone_id: milestone || null,
        acceptance_criteria: criteria.split("\n").map((l) => l.trim()).filter(Boolean),
      });
      onCreated(task);
    } catch { /* shown below */ }
  }

  return (
    <dialog ref={ref} aria-labelledby="new-task-title" onCancel={(e) => { e.preventDefault(); onClose(); }} className="dialog-panel m-auto w-[calc(100%-2rem)] max-w-xl rounded-xl border border-line bg-surface p-0 text-ink shadow-dialog backdrop:bg-black/40">
      <form onSubmit={submit}>
        <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-5">
          <div><h2 id="new-task-title" className="text-xl font-semibold tracking-tight">{t("New task")}</h2><p className="mt-1 text-sm text-ink-muted">{t("Describe the work. Its ID is created for you.")}</p></div>
          <Button variant="quiet" size="icon" onClick={onClose} aria-label={t("Close dialog")}><X size={18} /></Button>
        </div>
        <div className="space-y-4 px-6 py-5">
          <div><label htmlFor="task-title" className="field-label">{t("Title")} <span aria-hidden="true">*</span></label><input id="task-title" className="field-input" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} placeholder={t("Implement save migration")} autoFocus required /></div>
          <div><label htmlFor="task-description" className="field-label">{t("Description")} <span className="font-normal text-ink-subtle">{t("Optional")}</span></label><textarea id="task-description" className="field-input" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} /></div>
          <div><label htmlFor="task-criteria" className="field-label">{t("Acceptance criteria")} <span className="font-normal text-ink-subtle">{t("One per line, optional")}</span></label><textarea id="task-criteria" className="field-input" rows={3} value={criteria} onChange={(e) => setCriteria(e.target.value)} placeholder={t("Old saves load safely\nA migration test exists")} /></div>
          {milestones && milestones.length > 0 && <div><label htmlFor="task-milestone" className="field-label">{t("Milestone")}</label><select id="task-milestone" className="field-input" value={milestone} onChange={(e) => setMilestone(e.target.value)}><option value="">{t("No milestone")}</option>{milestones.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</select></div>}
          {create.isError && <p role="alert" className="text-sm text-danger-ink">{create.error.message}</p>}
        </div>
        <div className="flex justify-end gap-2 border-t border-line px-6 py-4"><Button variant="quiet" onClick={onClose}>{t("Cancel")}</Button><Button variant="primary" type="submit" disabled={create.isPending || !title.trim()}>{create.isPending ? t("Creating…") : t("Create task")}</Button></div>
      </form>
    </dialog>
  );
}

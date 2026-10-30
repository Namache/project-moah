import { Archive, X } from "lucide-react";
import type { Project } from "../types/project";
import { useArchiveProject } from "../hooks/useProjects";
import { Button } from "./ui";
import { useModalDialog } from "../hooks/useModalDialog";
import { notify } from "../lib/notify";
import { t } from "../lib/i18n";

export function ArchiveDialog({ project, onClose, onArchived }: { project: Project; onClose: () => void; onArchived: () => void }) {
  const dialogRef = useModalDialog();
  const archiveProject = useArchiveProject();

  async function handleArchive() {
    try {
      await archiveProject.mutateAsync(project.id);
      notify(t("{name} archived", { name: project.name }));
      onArchived();
    } catch {
      // The mutation error is shown in the dialog.
    }
  }

  return (
    <dialog ref={dialogRef} onCancel={(event) => { event.preventDefault(); onClose(); }} className="dialog-panel m-auto w-[calc(100%-2rem)] max-w-md rounded-xl border border-line bg-surface p-6 text-ink shadow-dialog backdrop:bg-black/40 sm:p-7" aria-labelledby="archive-title">
      <div className="flex justify-between gap-4">
        <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-warning-soft text-warning-ink"><Archive size={23} aria-hidden="true" /></span>
        <Button variant="quiet" className="!h-9 !min-h-9 !w-9 !p-0" onClick={onClose} aria-label={t("Close dialog")}><X size={18} /></Button>
      </div>
      <h2 id="archive-title" className="mt-5 text-xl font-semibold tracking-tight">{t("Archive {name}?", { name: project.name })}</h2>
      <p className="mt-2 text-sm leading-6 text-ink-muted">{t("The project will move out of your active workspace. Its Project Moah data stays available under Archived projects, and its source folder is never deleted.")}</p>
      {archiveProject.error && <p role="alert" className="mt-4 rounded-xl bg-danger-soft px-4 py-3 text-sm text-danger-ink">{archiveProject.error.message}</p>}
      <div className="mt-6 flex justify-end gap-2">
        <Button onClick={onClose}>{t("Cancel")}</Button>
        <Button variant="danger" onClick={handleArchive} disabled={archiveProject.isPending}>{archiveProject.isPending ? t("Archiving…") : t("Archive project")}</Button>
      </div>
    </dialog>
  );
}

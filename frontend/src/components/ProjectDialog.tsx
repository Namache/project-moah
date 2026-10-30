import { useState, type FormEvent } from "react";
import { FolderOpen, X } from "lucide-react";
import type { Project, ProjectInput, ProjectStatus } from "../types/project";
import { useCreateProject, useUpdateProject } from "../hooks/useProjects";
import { Button } from "./ui";
import { useModalDialog } from "../hooks/useModalDialog";
import { t } from "../lib/i18n";

const iconOptions = ["📁", "🧭", "🎮", "✨", "🌿", "💡", "🧪", "🎨"];

interface ProjectDialogProps {
  project?: Project;
  onClose: () => void;
  onSaved: (project: Project) => void;
}

export function ProjectDialog({ project, onClose, onSaved }: ProjectDialogProps) {
  const dialogRef = useModalDialog();
  const [name, setName] = useState(project?.name ?? "");
  const [description, setDescription] = useState(project?.description ?? "");
  const [icon, setIcon] = useState(project?.icon ?? "📁");
  const [accent, setAccent] = useState(project?.accent ?? "#35766d");
  const [rootPath, setRootPath] = useState(project?.root_path ?? "");
  const [status, setStatus] = useState<ProjectStatus>(project?.status ?? "active");
  const createProject = useCreateProject();
  const updateProject = useUpdateProject(project?.id ?? "");
  const mutation = project ? updateProject : createProject;


  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const input: ProjectInput = {
      name: name.trim(),
      description: description.trim() || null,
      icon: icon || null,
      accent,
      root_path: rootPath.trim() || null,
    };
    if (!input.name) return;
    try {
      const saved = project
        ? await updateProject.mutateAsync({ ...input, status })
        : await createProject.mutateAsync(input);
      onSaved(saved);
    } catch {
      // The mutation error is shown below the form.
    }
  }

  return (
    <dialog ref={dialogRef} aria-labelledby="project-dialog-title" onCancel={(event) => { event.preventDefault(); onClose(); }} className="dialog-panel m-auto w-[calc(100%-2rem)] max-w-xl rounded-xl border border-line bg-surface p-0 text-ink shadow-dialog backdrop:bg-black/40">
      <form onSubmit={handleSubmit} className="max-h-[min(90vh,800px)] overflow-y-auto">
        <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-5 sm:px-7">
          <div>
            <h2 id="project-dialog-title" className="text-xl font-semibold tracking-tight">{project ? t("Edit project") : t("New project")}</h2>
            <p className="mt-1 text-sm text-ink-muted">{t("Give this work a clear home in Project Moah.")}</p>
          </div>
          <Button variant="quiet" className="!h-9 !min-h-9 !w-9 !p-0" onClick={onClose} aria-label={t("Close dialog")}><X size={18} /></Button>
        </div>

        <div className="space-y-5 px-6 py-6 sm:px-7">
          <div>
            <label htmlFor="project-name" className="field-label">{t("Project name")} <span aria-hidden="true">*</span></label>
            <input id="project-name" className="field-input" value={name} onChange={(event) => setName(event.target.value)} required maxLength={120} autoFocus placeholder={t("e.g. Trailhead")} />
          </div>
          <div>
            <label htmlFor="project-description" className="field-label">{t("Description")} <span className="font-normal text-ink-subtle">{t("Optional")}</span></label>
            <textarea id="project-description" className="field-input min-h-24 resize-y" value={description} onChange={(event) => setDescription(event.target.value)} maxLength={1000} placeholder={t("What is this project about?")} />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="project-icon" className="field-label">{t("Icon")}</label>
              <select id="project-icon" className="field-input" value={icon} onChange={(event) => setIcon(event.target.value)}>
                <option value="">{t("No icon")}</option>
                {!iconOptions.includes(icon) && icon && <option value={icon}>{icon}</option>}
                {iconOptions.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="project-accent" className="field-label">{t("Accent color")}</label>
              <input id="project-accent" type="color" className="field-input !h-11 !p-1.5" value={/^#[0-9a-fA-F]{6}$/.test(accent) ? accent : "#35766d"} onChange={(event) => setAccent(event.target.value)} />
            </div>
          </div>
          {project && <div>
            <label htmlFor="project-status" className="field-label">{t("Status")}</label>
            <select id="project-status" className="field-input" value={status} onChange={(event) => setStatus(event.target.value as ProjectStatus)}>
              <option value="active">{t("Active")}</option>
              <option value="paused">{t("Paused")}</option>
              <option value="completed">{t("Completed")}</option>
              {project.status === "archived" && <option value="archived">{t("Archived")}</option>}
            </select>
          </div>}
          <div>
            <label htmlFor="project-path" className="field-label">{t("Repository path")} <span className="font-normal text-ink-subtle">{t("Optional")}</span></label>
            <div className="relative">
              <FolderOpen size={17} className="pointer-events-none absolute left-3 top-3 text-ink-subtle" aria-hidden="true" />
              <input id="project-path" className="field-input !pl-10" value={rootPath} onChange={(event) => setRootPath(event.target.value)} placeholder={t("/home/you/projects/trailhead")} autoComplete="off" />
            </div>
            {window.projectBrainDesktop?.chooseFolder && <Button className="mt-2" onClick={async () => { const chosen = await window.projectBrainDesktop?.chooseFolder?.().catch(() => null); if (chosen) setRootPath(chosen); }}><FolderOpen size={16} aria-hidden="true" />{t("Choose folder")}</Button>}
            <p className="mt-1.5 text-xs leading-5 text-ink-subtle">{t("You can add a path later. Project Moah reads only file names, Git status, and commit messages from this folder, and never changes it.")}</p>
          </div>
          {mutation.error && <p role="alert" className="rounded-xl bg-danger-soft px-4 py-3 text-sm text-danger-ink">{mutation.error.message}</p>}
        </div>
        <div className="flex justify-end gap-2 border-t border-line px-6 py-4 sm:px-7">
          <Button onClick={onClose}>{t("Cancel")}</Button>
          <Button variant="primary" type="submit" disabled={mutation.isPending || !name.trim()}>{mutation.isPending ? t("Saving…") : project ? t("Save changes") : t("Create project")}</Button>
        </div>
      </form>
    </dialog>
  );
}

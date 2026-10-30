import { Sparkles } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../ui";
import { useCreateProject, useUpdateProject } from "../../hooks/useProjects";
import { useCreateTask } from "../../hooks/useTasks";
import { writePref } from "../../lib/prefs";
import type { Project } from "../../types/project";
import { projectPath } from "../../lib/routes";
import { t } from "../../lib/i18n";

export const ONBOARDING_KEY = "pb-onboarding-done";

/** A short, skippable first-run guide. Every screen can be skipped, and nothing is required. */
export function Onboarding({ onDone }: { onDone: () => void }) {
  const [step, setStep] = useState(1);
  const [project, setProject] = useState<Project | null>(null);
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const [task, setTask] = useState("");
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const heading = useRef<HTMLHeadingElement>(null);
  const createProject = useCreateProject();
  const updateProject = useUpdateProject(project?.id ?? "");
  const createTask = useCreateTask(project?.id ?? "");
  const canChoose = Boolean(window.projectBrainDesktop?.chooseFolder);

  function go(next: number) { setError(""); setStep(next); requestAnimationFrame(() => (document.querySelector<HTMLElement>("[data-onboarding-focus]") ?? heading.current)?.focus()); }
  function finish(to?: string) { writePref(ONBOARDING_KEY, "1"); onDone(); navigate(to ?? (project ? projectPath(project.id) : "/projects")); }
  const fail = (e: unknown) => setError(e instanceof Error ? e.message : t("Something went wrong. Please try again."));

  async function submitProject(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    try { setProject(await createProject.mutateAsync({ name: name.trim() })); go(3); } catch (e) { fail(e); }
  }
  async function saveRepository() {
    if (!path.trim()) return go(4);
    try { await updateProject.mutateAsync({ root_path: path.trim() }); go(4); } catch (e) { fail(e); }
  }
  async function submitTask(event: FormEvent) {
    event.preventDefault();
    if (!task.trim()) return;
    try { await createTask.mutateAsync({ title: task.trim() }); go(5); } catch (e) { fail(e); }
  }

  const skip = <button type="button" onClick={() => finish()} className="text-sm font-medium text-ink-muted underline hover:text-forest focus-visible:outline-2 focus-visible:outline-forest">{t("Skip setup")}</button>;
  const title = { 1: t("Welcome to Project Moah 👋"), 2: t("Create your first project"), 3: t("Connect a repository"), 4: t("Create your first task"), 5: t("Connect an AI") }[step];

  return (
    <section aria-labelledby="onboarding-title" className="mx-auto max-w-xl rounded-[28px] border border-line bg-surface p-8 shadow-card sm:p-10">
      <p className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.18em] text-forest"><Sparkles size={15} aria-hidden="true" />{t("Step {step} of {count}", { step, count: 5 })}</p>
      <h1 id="onboarding-title" ref={heading} tabIndex={-1} className="mt-3 text-2xl font-semibold tracking-tight text-ink outline-none">{title}</h1>

      {step === 1 && <>
        <p className="mt-4 text-sm leading-7 text-ink-muted">{t("Project Moah keeps your tasks, decisions and AI development memory organized. It helps coding agents continue work without re-reading your entire project history. Everything stays on this computer.")}</p>
        <div className="mt-8 flex items-center justify-between"><Button variant="primary" onClick={() => go(2)}>{t("Get started")}</Button>{skip}</div>
      </>}

      {step === 2 && <form onSubmit={submitProject}>
        <p className="mt-4 text-sm leading-7 text-ink-muted">{t("A project is a separate home for one product or codebase.")}</p>
        <label htmlFor="onb-name" className="field-label mt-5">{t("Project name")}</label>
        <input id="onb-name" className="field-input" value={name} onChange={(e) => setName(e.target.value)} placeholder={t("Trailhead")} maxLength={120} data-onboarding-focus />
        {error && <p role="alert" className="mt-3 text-sm text-danger-ink">{error}</p>}
        <div className="mt-8 flex items-center justify-between"><Button variant="primary" type="submit" disabled={!name.trim() || createProject.isPending}>{t("Continue")}</Button>{skip}</div>
      </form>}

      {step === 3 && <>
        <p className="mt-4 text-sm leading-7 text-ink-muted">{t("Pick the folder your code lives in. Project Moah only reads file names, Git status and commit messages, and never changes your code. You can do this later.")}</p>
        {canChoose && <Button className="mt-5" onClick={async () => { const chosen = await window.projectBrainDesktop?.chooseFolder?.(t("Choose the project's repository folder")).catch(() => null); if (chosen) setPath(chosen); }}>{t("Choose folder")}</Button>}
        <label htmlFor="onb-path" className="field-label mt-5">{t("Folder path")}</label>
        <input id="onb-path" data-onboarding-focus className="field-input" value={path} onChange={(e) => setPath(e.target.value)} placeholder={t("/home/you/projects/trailhead")} />
        {error && <p role="alert" className="mt-3 text-sm text-danger-ink">{error}</p>}
        <div className="mt-8 flex items-center justify-between"><div className="flex gap-2"><Button variant="primary" onClick={() => void saveRepository()} disabled={updateProject.isPending}>{path.trim() ? t("Save and continue") : t("Continue")}</Button><Button variant="quiet" onClick={() => go(4)}>{t("Skip for now")}</Button></div>{skip}</div>
      </>}

      {step === 4 && <form onSubmit={submitTask}>
        <p className="mt-4 text-sm leading-7 text-ink-muted">{t("Tasks keep you and your agents aligned on what to build next. For example:")} <em>{t("\"Implement save migration\"")}</em>.</p>
        <label htmlFor="onb-task" className="field-label mt-5">{t("Task title")}</label>
        <input id="onb-task" className="field-input" value={task} onChange={(e) => setTask(e.target.value)} maxLength={200} data-onboarding-focus />
        {error && <p role="alert" className="mt-3 text-sm text-danger-ink">{error}</p>}
        <div className="mt-8 flex items-center justify-between"><div className="flex gap-2"><Button variant="primary" type="submit" disabled={!task.trim() || createTask.isPending}>{t("Create task")}</Button><Button variant="quiet" onClick={() => go(5)}>{t("Skip for now")}</Button></div>{skip}</div>
      </form>}

      {step === 5 && <>
        <p className="mt-4 text-sm leading-7 text-ink-muted">{t("Connect a coding agent so it can read your project's context. Each guide has the exact commands for your project.")}</p>
        <div className="mt-6 flex flex-wrap gap-2">
          <Button onClick={() => finish("/help/claude")}>{t("Set up Claude")}</Button>
          <Button onClick={() => finish("/help/codex")}>{t("Set up Codex")}</Button>
          <Button variant="quiet" onClick={() => finish()}>{t("Do this later")}</Button>
        </div>
      </>}
    </section>
  );
}

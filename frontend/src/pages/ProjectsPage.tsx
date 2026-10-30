import { useMemo, useState } from "react";
import { Archive, FolderKanban, Plus, Search } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { ArchiveDialog } from "../components/ArchiveDialog";
import { ProjectCard } from "../components/ProjectCard";
import { ProjectDialog } from "../components/ProjectDialog";
import { AgentSync, useAgentFolders } from "../components/AgentSync";
import { Button, EmptyState, ErrorState, LoadingState, PageHeading, SegmentedControl } from "../components/ui";
import { useProjects, useRestoreProject } from "../hooks/useProjects";
import { useOverviews } from "../hooks/useTasks";
import type { Project } from "../types/project";
import { notify } from "../lib/notify";
import { projectPath } from "../lib/routes";
import { t } from "../lib/i18n";

export function ProjectsPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const projects = useProjects();
  const overviewById = new Map((useOverviews().data ?? []).map((o) => [o.project_id, o]));
  const restoreProject = useRestoreProject();
  // Folders waiting for an answer go first; otherwise sync is a quiet line under the projects.
  const agentFolders = useAgentFolders().data?.folders;
  const foldersWaiting = Array.isArray(agentFolders) && agentFolders.some((f) => f.status === "suggested");
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"current" | "archived">("current");
  const [creating, setCreating] = useState(() => new URLSearchParams(location.search).has("new"));
  const [editing, setEditing] = useState<Project | null>(null);
  const [archiving, setArchiving] = useState<Project | null>(null);
  const [restoreError, setRestoreError] = useState("");

  const counts = useMemo(() => ({
    current: projects.data?.filter((project) => project.status !== "archived").length ?? 0,
    archived: projects.data?.filter((project) => project.status === "archived").length ?? 0,
  }), [projects.data]);
  const visible = useMemo(() => (projects.data ?? [])
    .filter((project) => (view === "archived") === (project.status === "archived"))
    .filter((project) => `${project.name} ${project.description ?? ""}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))
    .sort((a, b) => a.name.localeCompare(b.name)), [projects.data, search, view]);

  function closeCreate() {
    setCreating(false);
    if (location.search) navigate("/projects", { replace: true });
  }

  async function restore(project: Project) {
    setRestoreError("");
    try {
      await restoreProject.mutateAsync(project.id);
      notify(t("{name} restored", { name: project.name }));
    } catch (error) {
      setRestoreError(error instanceof Error ? error.message : t("The project could not be restored."));
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHeading title={t("Projects")} />
        <Button variant="primary" onClick={() => setCreating(true)}><Plus size={17} aria-hidden="true" />{t("New project")}</Button>
      </div>

      {foldersWaiting && <AgentSync />}

      <div className="mt-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <SegmentedControl label={t("Project view")} value={view} onChange={setView} className="self-start" options={[{ value: "current", label: t("Current"), count: counts.current }, { value: "archived", label: t("Archived"), count: counts.archived }]} />
        <div className="relative w-full sm:max-w-xs">
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-subtle" aria-hidden="true" />
          <label htmlFor="project-search" className="sr-only">{t("Search projects")}</label>
          <input id="project-search" type="search" className="field-input !pl-10" placeholder={t("Search projects")} value={search} onChange={(event) => setSearch(event.target.value)} />
        </div>
      </div>

      <div className="mt-6">
        {restoreError && <div role="alert" className="mb-4"><ErrorState title={t("Could not restore project")} message={restoreError} /></div>}
        {projects.isPending ? <LoadingState /> : projects.isError ? <ErrorState title={t("Projects are unavailable")} message={projects.error.message} onRetry={() => void projects.refetch()} /> : visible.length ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">{visible.map((project) => <ProjectCard key={project.id} project={project} overview={overviewById.get(project.id)} onEdit={setEditing} onArchive={setArchiving} onRestore={(item) => void restore(item)} />)}</div>
        ) : search.trim() ? (
          <EmptyState icon={<Search size={26} />} title={t("No matching projects")}>{t("Try a different name or description, or switch between Current and Archived.")}</EmptyState>
        ) : view === "archived" ? (
          <EmptyState icon={<Archive size={26} />} title={t("No archived projects")}>{t("Archived projects will appear here. You can restore them whenever you need them.")}</EmptyState>
        ) : (
          <EmptyState icon={<FolderKanban size={26} />} title={t("Start with your first project")} action={<Button variant="primary" onClick={() => setCreating(true)}><Plus size={17} />{t("Create project")}</Button>}>
            {t("Projects keep work separate, so each one can grow its own tasks and development memory.")}
          </EmptyState>
        )}
      </div>

      {!foldersWaiting && <AgentSync />}

      {creating && <ProjectDialog onClose={closeCreate} onSaved={(project) => { setCreating(false); navigate(projectPath(project.id)); }} />}
      {editing && <ProjectDialog key={editing.id} project={editing} onClose={() => setEditing(null)} onSaved={() => setEditing(null)} />}
      {archiving && <ArchiveDialog project={archiving} onClose={() => setArchiving(null)} onArchived={() => setArchiving(null)} />}
    </div>
  );
}

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
      notify(`${project.name} restored`);
    } catch (error) {
      setRestoreError(error instanceof Error ? error.message : "The project could not be restored.");
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHeading title="Projects" />
        <Button variant="primary" onClick={() => setCreating(true)}><Plus size={17} aria-hidden="true" />New project</Button>
      </div>

      {foldersWaiting && <AgentSync />}

      <div className="mt-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <SegmentedControl label="Project view" value={view} onChange={setView} className="self-start" options={[{ value: "current", label: "Current", count: counts.current }, { value: "archived", label: "Archived", count: counts.archived }]} />
        <div className="relative w-full sm:max-w-xs">
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-subtle" aria-hidden="true" />
          <label htmlFor="project-search" className="sr-only">Search projects</label>
          <input id="project-search" type="search" className="field-input !pl-10" placeholder="Search projects" value={search} onChange={(event) => setSearch(event.target.value)} />
        </div>
      </div>

      <div className="mt-6">
        {restoreError && <div role="alert" className="mb-4"><ErrorState title="Could not restore project" message={restoreError} /></div>}
        {projects.isPending ? <LoadingState /> : projects.isError ? <ErrorState title="Projects are unavailable" message={projects.error.message} onRetry={() => void projects.refetch()} /> : visible.length ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">{visible.map((project) => <ProjectCard key={project.id} project={project} overview={overviewById.get(project.id)} onEdit={setEditing} onArchive={setArchiving} onRestore={(item) => void restore(item)} />)}</div>
        ) : search.trim() ? (
          <EmptyState icon={<Search size={26} />} title="No matching projects">Try a different name or description, or switch between Current and Archived.</EmptyState>
        ) : view === "archived" ? (
          <EmptyState icon={<Archive size={26} />} title="No archived projects">Archived projects will appear here. You can restore them whenever you need them.</EmptyState>
        ) : (
          <EmptyState icon={<FolderKanban size={26} />} title="Start with your first project" action={<Button variant="primary" onClick={() => setCreating(true)}><Plus size={17} />Create project</Button>}>
            Projects keep work separate, so each one can grow its own tasks and development memory.
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

import { useState } from "react";
import { Activity, Archive, BookOpen, Bot, FolderOpen, Inbox, LayoutDashboard, ListTodo, Pencil, RotateCcw, type LucideIcon } from "lucide-react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { ArchiveDialog } from "../components/ArchiveDialog";
import { ProjectDialog } from "../components/ProjectDialog";
import { ContextInspector } from "../components/context/ContextInspector";
import { GettingStarted } from "../components/onboarding/GettingStarted";
import { FocusCard } from "../components/tasks/FocusCard";
import { ProjectCheckpoints } from "../components/checkpoints/CheckpointsSection";
import { ProjectActivity } from "../components/activity/ProjectActivity";
import { RecentActivity } from "../components/activity/RecentActivity";
import { ReviewPage } from "./ReviewPage";
import { usePendingProposals } from "../hooks/useProposals";
import { FilesPage } from "./FilesPage";
import { TasksPage } from "./TasksPage";
import { MemoryPage } from "./MemoryPage";
import { useMilestones, useTasks } from "../hooks/useTasks";
import { boardColumns } from "../types/task";
import { Button, ErrorState, Menu, ProgressBar, ProjectTile, StatusBadge, Widget, toneClasses, type MenuItem } from "../components/ui";
import { taskStatusStyle } from "../lib/tones";
import { useProject, useRestoreProject } from "../hooks/useProjects";
import type { Project } from "../types/project";
import { notify } from "../lib/notify";
import { projectPath, projectSections, type ProjectSection } from "../lib/routes";

const NAV = projectSections;
const sectionIcons: Record<ProjectSection, LucideIcon> = { "": LayoutDashboard, tasks: ListTodo, memory: BookOpen, context: Bot, review: Inbox, files: FolderOpen, activity: Activity };
const isSection = (value: string): value is ProjectSection => NAV.some((item) => item.path === value);

function Overview({ project }: { project: Project }) {
  const tasks = useTasks(project.id);
  const milestones = useMilestones(project.id);
  const focus = tasks.data?.find((t) => t.id === project.current_focus_task_id) ?? null;
  const milestone = milestones.data?.find((m) => m.status === "active") ?? milestones.data?.find((m) => m.status === "planned") ?? null;
  const percent = milestone && milestone.task_count ? Math.round((milestone.completed_task_count / milestone.task_count) * 100) : 0;
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(280px,1fr)]">
      <div className="space-y-4">
      <GettingStarted project={project} />
      <FocusCard projectId={project.id} task={focus} />
      <Widget title="Tasks" icon={ListTodo} to={projectPath(project.id, "tasks")} linkLabel="Open the board" action={milestone && <span className="text-xs text-ink-muted">{milestone.name}: {percent}% done</span>}>
        {milestone && <ProgressBar value={percent} label={`${milestone.name} progress`} />}
        <div className="@container mt-4">
          <ul className="grid grid-cols-3 gap-2 @lg:grid-cols-6">
            {boardColumns.map((c) => {
              const { tone, icon: Icon } = taskStatusStyle[c.status];
              return <li key={c.status}><Link to={projectPath(project.id, "tasks")} className="flex flex-col gap-1 rounded-lg bg-canvas px-3 py-2.5 hover:bg-hover focus-visible:outline-2 focus-visible:outline-forest">
                <span className="text-xl font-semibold tabular-nums text-ink">{tasks.data?.filter((t) => t.status === c.status).length ?? "–"}</span>
                <span className={`flex items-center gap-1 whitespace-nowrap text-xs font-medium ${toneClasses[tone].text}`}><Icon size={12} aria-hidden="true" />{c.label}</span>
              </Link></li>;
            })}
          </ul>
        </div>
      </Widget>
      <ProjectCheckpoints projectId={project.id} archived={project.status === "archived"} />
      </div>
      <div className="space-y-4">
      <RecentActivity projectId={project.id} />
      </div>
    </div>
  );
}

export function ProjectPage() {
  const { projectId = "", section } = useParams();
  const navigate = useNavigate();
  const projectQuery = useProject(projectId);
  const pendingCount = usePendingProposals().data?.by_project?.[projectId] ?? 0;
  const restoreProject = useRestoreProject();
  const [editing, setEditing] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [restoreError, setRestoreError] = useState("");

  if (section && !isSection(section)) return <Navigate to={`/projects/${projectId}`} replace />;
  if (projectQuery.isPending) return <div role="status" className="space-y-4" aria-label="Loading project"><div className="h-20 w-2/3 animate-pulse rounded-xl bg-surface" /><div className="h-72 animate-pulse rounded-xl bg-surface" /></div>;
  if (projectQuery.isError) return <ErrorState title="Project could not be opened" message={projectQuery.error.message} onRetry={() => void projectQuery.refetch()} />;

  const project = projectQuery.data;
  const menuItems: MenuItem[] = [{ label: "Edit", icon: Pencil, onSelect: () => setEditing(true) }];
  if (project.status !== "archived") menuItems.push({ label: "Archive", icon: Archive, onSelect: () => setArchiving(true) });

  async function restore() {
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
      <header className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3.5">
          <ProjectTile project={project} className="w-12 flex-none !rounded-lg !text-2xl [&_svg]:size-6" />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2"><h1 className="min-w-0 break-words text-2xl font-semibold tracking-tight text-ink">{project.name}</h1><StatusBadge status={project.status} /></div>
            <p className="mt-0.5 flex min-w-0 items-center gap-1.5 text-sm text-ink-muted">
              {project.description && <span className="truncate" title={project.description}>{project.description}</span>}
              {project.description && project.root_path && <span aria-hidden="true">·</span>}
              {project.root_path && <span className="flex min-w-0 items-center gap-1 text-ink-subtle" title={project.root_path}><FolderOpen size={13} className="flex-none" aria-hidden="true" /><span className="truncate">{project.root_path}</span></span>}
            </p>
          </div>
        </div>
        <div className="flex flex-none items-center gap-1">
          {project.status === "archived" && <Button variant="primary" size="sm" onClick={() => void restore()} disabled={restoreProject.isPending}><RotateCcw size={15} aria-hidden="true" />Restore</Button>}
          <Menu label={`Actions for ${project.name}`} items={menuItems} />
        </div>
      </header>

      {project.status === "archived" && <div className="mt-4 rounded-xl bg-warning-soft px-4 py-3 text-sm text-warning-ink">This project is archived. Restore it to bring it back to your active workspace.</div>}
      {restoreError && <div className="mt-4"><ErrorState title="Could not restore project" message={restoreError} /></div>}

      <nav aria-label="Project sections" className="mt-5 flex gap-1 overflow-x-auto border-b border-line">
        {NAV.map((item) => {
          const Icon = sectionIcons[item.path];
          return <Link
            key={item.path}
            to={projectPath(project.id, item.path)}
            aria-current={(section ?? "") === item.path ? "page" : undefined}
            className={`section-tab inline-flex items-center gap-1.5 ${(section ?? "") === item.path ? "section-tab-active" : ""}`}
          ><Icon size={15} aria-hidden="true" />{item.label}{item.path === "review" && pendingCount ? <span className="rounded-full bg-primary px-1.5 text-xs font-semibold leading-5 text-white" aria-label={`${pendingCount} waiting`}>{pendingCount}</span> : null}</Link>;
        })}
      </nav>

      <div className="mt-6">
        {section === "tasks" ? <TasksPage projectId={project.id} archived={project.status === "archived"} /> : section === "memory" ? <MemoryPage projectId={project.id} archived={project.status === "archived"} /> : section === "review" ? <ReviewPage projectId={project.id} archived={project.status === "archived"} /> : section === "files" ? <FilesPage projectId={project.id} archived={project.status === "archived"} /> : section === "context" ? <ContextInspector projectId={project.id} focusTaskId={project.current_focus_task_id} /> : section === "activity" ? <ProjectActivity projectId={project.id} /> : <Overview project={project} />}
      </div>

      {editing && <ProjectDialog project={project} onClose={() => setEditing(false)} onSaved={() => setEditing(false)} />}
      {archiving && <ArchiveDialog project={project} onClose={() => setArchiving(false)} onArchived={() => { setArchiving(false); navigate("/projects"); }} />}
    </div>
  );
}

import { Archive, FolderOpen, Pencil, RotateCcw } from "lucide-react";
import { Link } from "react-router-dom";
import type { Project } from "../types/project";
import type { ProjectOverview } from "../types/task";
import { statusLabels } from "../types/task";
import { taskStatusStyle } from "../lib/tones";
import { Menu, ProgressBar, ProjectTile, StatusBadge, toneClasses, type MenuItem } from "./ui";
import { projectPath } from "../lib/routes";
import { t } from "../lib/i18n";

interface ProjectCardProps {
  project: Project;
  overview?: ProjectOverview;
  onEdit?: (project: Project) => void;
  onArchive?: (project: Project) => void;
  onRestore?: (project: Project) => void;
}

/** A project on the Projects page: its tile, progress and current task. The whole card opens it; rare actions sit behind "⋯". */
export function ProjectCard({ project, overview, onEdit, onArchive, onRestore }: ProjectCardProps) {
  const items: MenuItem[] = [];
  if (onEdit) items.push({ label: t("Edit"), icon: Pencil, onSelect: () => onEdit(project) });
  if (project.status === "archived") { if (onRestore) items.push({ label: t("Restore"), icon: RotateCcw, onSelect: () => onRestore(project) }); }
  else if (onArchive) items.push({ label: t("Archive"), icon: Archive, onSelect: () => onArchive(project) });
  const milestone = overview?.active_milestone ?? null;
  const percent = milestone?.task_count ? Math.round((milestone.completed_task_count / milestone.task_count) * 100) : 0;
  const focus = overview?.focus_task ?? null;
  const FocusIcon = focus ? taskStatusStyle[focus.status].icon : null;

  return (
    <article className="relative flex min-w-0 flex-col rounded-xl border border-line bg-surface shadow-card transition-shadow hover:shadow-card-hover">
      <Link to={projectPath(project.id)} className="flex flex-1 flex-col gap-4 rounded-xl p-4 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-forest">
        <span className="flex min-w-0 items-start gap-3.5 pr-8">
          <ProjectTile project={project} className="w-14 flex-none !rounded-lg !text-2xl [&_svg]:size-6" />
          <span className="min-w-0">
            <span className="flex flex-wrap items-center gap-2"><span className="truncate text-base font-semibold tracking-tight text-ink" title={project.name}>{project.name}</span><StatusBadge status={project.status} /></span>
            <span className="mt-1 line-clamp-2 text-sm leading-5 text-ink-muted">{project.description || t("No description yet.")}</span>
          </span>
        </span>
        {milestone && <span className="block text-xs text-ink-muted"><span className="mb-1.5 flex justify-between gap-2"><span className="truncate">{milestone.name}</span><span className="tabular-nums">{percent}%</span></span><ProgressBar value={percent} label={t("{name} progress", { name: milestone.name })} /></span>}
        <span className="mt-auto flex min-w-0 items-center gap-2 border-t border-line pt-3 text-xs text-ink-muted">
          {focus && FocusIcon
            ? <><FocusIcon size={14} className={`flex-none ${toneClasses[taskStatusStyle[focus.status].tone].text}`} aria-label={statusLabels[focus.status]} /><span className="truncate"><span className="font-medium text-ink">{focus.human_id}</span> {focus.title}</span></>
            : <><FolderOpen size={14} className="flex-none" aria-hidden="true" /><span className="truncate" title={project.root_path || undefined}>{project.root_path || t("No folder linked")}</span></>}
        </span>
      </Link>
      {items.length > 0 && <div className="absolute right-2 top-2"><Menu label={t("Actions for {name}", { name: project.name })} items={items} /></div>}
    </article>
  );
}

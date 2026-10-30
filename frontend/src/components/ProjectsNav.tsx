import { ChevronDown, FolderKanban } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink } from "react-router-dom";
import { readPref, writePref } from "../lib/prefs";
import type { Project } from "../types/project";
import { projectPath } from "../lib/routes";
import { ProjectAvatar } from "./ui";
import { t } from "../lib/i18n";

const OPEN_KEY = "pb-sidebar-projects-open";

/** Projects in the sidebar: the link to the Projects page plus a list of every project for quick access. */
export function ProjectsNav({ projects, pending, wide, currentId }: { projects: Project[]; pending: Record<string, number>; wide: boolean; currentId: string }) {
  const [open, setOpen] = useState(() => readPref(OPEN_KEY) !== "0");
  const [flyout, setFlyout] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const sorted = [...projects].sort((a, b) => (b.last_opened_at ?? b.updated_at).localeCompare(a.last_opened_at ?? a.updated_at));
  const toggle = () => { setOpen((v) => { writePref(OPEN_KEY, v ? "0" : "1"); return !v; }); };

  useEffect(() => {
    if (!flyout) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !box.current?.contains(event.target as Node)) setFlyout(false);
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", close);
    return () => { window.removeEventListener("mousedown", close); window.removeEventListener("keydown", close); };
  }, [flyout]);

  const list = (onPick?: () => void) => (
    <ul className="space-y-px">
      {sorted.map((p) => (
        <li key={p.id}>
          <NavLink to={projectPath(p.id)} onClick={onPick} className={() => `project-nav-link !flex items-center gap-2.5 !min-w-0 ${currentId === p.id ? "project-nav-link-active" : ""}`} title={p.name}>
            <ProjectAvatar project={p} size="small" />
            <span className="min-w-0 flex-1 truncate">{p.name}</span>
            {pending[p.id] ? <span className="flex-none rounded-full bg-side-accent px-1.5 text-xs font-semibold leading-5 text-side-accent-ink" aria-label={t("{count} waiting for your decision", { count: pending[p.id] })}>{pending[p.id]}</span> : null}
          </NavLink>
        </li>
      ))}
      <li><Link to="/projects" onClick={onPick} className="project-nav-link !min-w-0 text-xs">{t("All projects")}</Link></li>
    </ul>
  );

  if (!wide) {
    return (
      <div ref={box} className="relative">
        <button type="button" title={t("Projects")} aria-label={t("Projects")} aria-expanded={flyout} aria-haspopup="true" onClick={() => setFlyout((v) => !v)} className={`sidebar-link w-full ${flyout ? "sidebar-link-active" : ""}`}><FolderKanban size={18} strokeWidth={1.9} aria-hidden="true" /></button>
        {flyout && <nav aria-label={t("Your projects")} className="absolute left-full top-0 z-30 ml-2 w-60 rounded-xl bg-side p-2 shadow-card-hover ring-1 ring-side-line">{list(() => setFlyout(false))}</nav>}
      </div>
    );
  }
  return (
    <div>
      <div className="group flex items-center">
        <NavLink to="/projects" end className={({ isActive }) => `sidebar-section flex-1 rounded-md py-1 hover:!text-side-ink focus-visible:outline-2 focus-visible:outline-side-accent ${isActive ? "!text-side-ink" : ""}`}>{t("Projects")}</NavLink>
        <button type="button" onClick={toggle} aria-expanded={open} aria-controls="sidebar-project-list" aria-label={open ? t("Hide project list") : t("Show project list")} className="rounded-md p-1 text-side-muted hover:bg-side-hover hover:text-side-ink focus-visible:outline-2 focus-visible:outline-side-accent"><ChevronDown size={14} className={`transition-transform ${open ? "" : "-rotate-90"}`} aria-hidden="true" /></button>
      </div>
      {open && <nav id="sidebar-project-list" aria-label={t("Your projects")} className="mt-1">{list()}</nav>}
    </div>
  );
}

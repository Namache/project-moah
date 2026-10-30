import { BookOpen, ChevronDown, FolderPlus, ListPlus, Plus, Search, Sparkles, type LucideIcon } from "lucide-react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { useProject, useProjects } from "../hooks/useProjects";
import { usePendingProposals } from "../hooks/useProposals";
import { useKnowledgeUpdates } from "../hooks/useGraph";
import { CommandPalette } from "./CommandPalette";
import { primaryNav, secondaryNav, supportNav } from "./navItems";
import { ProjectsNav } from "./ProjectsNav";
import { SidebarResizer, useSidebarWidth } from "./SidebarResizer";
import { Notices } from "./Notices";
import { Menu, type MenuItem } from "./ui";
import { projectPath } from "../lib/routes";
import { useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import { t } from "../lib/i18n";

// Below the lg breakpoint the sidebar is a narrow icon rail, so labels are visually hidden but still named.
function WorkspaceLink({ label, to, icon: Icon, badge, end }: { label: string; to: string; icon: LucideIcon; badge?: number; end?: boolean }) {
  return (
    <NavLink to={to} end={end ?? to === "/"} title={label} className={({ isActive }) => `sidebar-link ${isActive ? "sidebar-link-active" : ""}`}>
      <span className="relative flex">
        <Icon size={17} strokeWidth={1.9} aria-hidden="true" />
        {badge ? <span className="absolute -right-2 -top-2 h-2 w-2 rounded-full bg-side-accent lg:hidden" aria-hidden="true" /> : null}
      </span>
      <span className="sr-only lg:not-sr-only">{label}</span>
      {badge ? <span className="ml-auto hidden min-w-5 rounded-full bg-side-accent px-1.5 text-center text-xs font-semibold leading-5 text-side-accent-ink lg:inline" aria-label={t("{count} waiting", { count: badge })}>{badge}</span> : null}
    </NavLink>
  );
}

const WIDE_QUERY = "(min-width: 1024px)";

// Matches Tailwind's lg breakpoint. Without matchMedia (tests, very old engines) the wide layout is assumed.
function useWideLayout() {
  return useSyncExternalStore(
    (onChange) => {
      if (typeof window.matchMedia !== "function") return () => {};
      const query = window.matchMedia(WIDE_QUERY);
      query.addEventListener("change", onChange);
      return () => query.removeEventListener("change", onChange);
    },
    () => typeof window.matchMedia !== "function" || window.matchMedia(WIDE_QUERY).matches,
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation();
  const selectedId = location.pathname.match(/^\/projects\/([^/]+)/)?.[1] ?? "";
  const projects = useProjects();
  const pending = usePendingProposals().data;
  useKnowledgeUpdates();
  const detail = useProject(selectedId);
  const selectedProject = detail.data ?? projects.data?.find((project) => project.id === selectedId);
  const availableProjects = projects.data?.filter((project) => project.status !== "archived") ?? [];

  const wide = useWideLayout();
  const [sidebarWidth, setSidebarWidth] = useSidebarWidth();
  const pendingTotal = pending?.total ?? 0;
  const [paletteOpen, setPaletteOpen] = useState(false);
  const navigate = useNavigate();
  // New tasks and memories go to the project on screen, otherwise to the one opened last.
  const target = selectedProject && selectedProject.status !== "archived" ? selectedProject
    : [...availableProjects].sort((a, b) => (b.last_opened_at ?? b.updated_at).localeCompare(a.last_opened_at ?? a.updated_at))[0];
  const newItems: MenuItem[] = [
    { label: target ? t("New task in {name}", { name: target.name }) : t("New task"), icon: ListPlus, disabled: !target, onSelect: () => target && navigate(projectPath(target.id, "tasks", { new: "1" })) },
    { label: target ? t("New memory in {name}", { name: target.name }) : t("New memory"), icon: BookOpen, disabled: !target, onSelect: () => target && navigate(projectPath(target.id, "memory", { new: "1" })) },
    { label: t("New project"), icon: FolderPlus, onSelect: () => navigate("/projects?new=1") },
  ];

  useEffect(() => {
    // Ctrl+K (Cmd+K on a Mac) toggles the palette anywhere; "/" opens it unless the person is already typing.
    function onKey(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
        return;
      }
      const target = event.target as HTMLElement | null;
      if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) return;
      if (target && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))) return;
      event.preventDefault();
      setPaletteOpen(true);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="flex min-h-screen bg-canvas">
      <a href="#main-content" className="skip-link">{t("Skip to content")}</a>
      {/* The column stretches with the page so its background and border never stop short; its content stays in view while the page scrolls. */}
      <aside className="relative z-10 w-16 flex-none bg-side text-side-ink" style={wide ? { width: sidebarWidth } : undefined}>
        <div className="sticky top-0 flex h-screen flex-col items-center overflow-y-auto px-2 py-4 lg:items-stretch lg:px-3">
          <Link to="/" className="flex items-center gap-2.5 rounded-lg lg:px-1.5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-side-accent" aria-label={t("Project Moah home")}>
            <span className="flex h-8 w-8 flex-none items-center justify-center rounded-lg bg-side-new text-white"><Sparkles size={17} strokeWidth={1.9} aria-hidden="true" /></span>
            <span className="hidden text-base font-semibold tracking-tight lg:inline">Project Moah</span>
          </Link>

          <div className="mt-5 w-full">
            <Menu label={t("Create new")} items={newItems} align="left" wide
              triggerClassName="flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-side-new px-3 text-sm font-semibold text-white shadow-card transition-colors hover:bg-side-new-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-side-accent lg:justify-start"
              trigger={<><Plus size={17} strokeWidth={2.4} aria-hidden="true" /><span className="sr-only lg:not-sr-only">{t("New")}</span><ChevronDown size={15} className="ml-auto hidden opacity-80 lg:block" aria-hidden="true" /></>} />
          </div>

          <button type="button" onClick={() => setPaletteOpen(true)} aria-keyshortcuts="Control+K /" aria-haspopup="dialog" title={t("Search or jump to (Ctrl+K)")}
            className="mt-2 flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-side-hover text-sm text-side-muted transition-colors hover:bg-side-active hover:text-side-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-side-accent lg:justify-start lg:px-2.5">
            <Search size={15} aria-hidden="true" />
            <span className="sr-only lg:not-sr-only">{t("Search or jump to…")}</span>
            <kbd className="ml-auto hidden rounded border border-side-line px-1 font-sans text-xs lg:inline" aria-hidden="true">Ctrl K</kbd>
          </button>

          <nav aria-label={t("Workspace")} className="mt-5 w-full">
            <div className="space-y-px">
              {primaryNav.map((item) => <WorkspaceLink key={item.to} {...item} badge={item.to === "/review" ? pendingTotal : undefined} />)}
            </div>
            <div className="mt-5">
              <ProjectsNav projects={availableProjects} pending={pending?.by_project ?? {}} wide={wide} currentId={selectedId} />
            </div>
            <div className="mt-5 space-y-px border-t border-side-line pt-4">
              {secondaryNav.map((item) => <WorkspaceLink key={item.to} {...item} />)}
            </div>
          </nav>

          <nav aria-label={t("Support")} className="mt-auto w-full space-y-px pt-6">
            {supportNav.map((item) => <WorkspaceLink key={item.to} {...item} />)}
            <p className="hidden items-center gap-2 px-2.5 pt-3 text-xs text-side-muted lg:flex" title={t("Nothing leaves this computer")}>
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-side-accent" aria-hidden="true" />
              {t("Stays on this computer")}
            </p>
          </nav>
        </div>
      </aside>

      {wide && <SidebarResizer width={sidebarWidth} onResize={setSidebarWidth} />}
      <div className="min-w-0 flex-1">
        <main id="main-content" tabIndex={-1} className="mx-auto max-w-[1280px] px-5 py-6 outline-none sm:px-8 sm:py-8 lg:px-10">
          {children}
        </main>
      </div>
      <Notices />
      {paletteOpen && <CommandPalette projects={availableProjects} current={selectedProject} onClose={() => setPaletteOpen(false)} />}
    </div>
  );
}

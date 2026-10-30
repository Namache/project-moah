import { ArrowRight, CornerDownLeft, FileSearch, Plus, Search } from "lucide-react";
import { useId, useMemo, useState, type KeyboardEvent, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useModalDialog } from "../hooks/useModalDialog";
import { projectPath, projectSections } from "../lib/routes";
import { setTheme, themeChoices } from "../lib/theme";
import type { Project } from "../types/project";
import { primaryNav, projectsNavItem, secondaryNav, supportNav } from "./navItems";
import { ProjectAvatar } from "./ui";
import { t } from "../lib/i18n";

/** A command either opens a page (to) or does something in place (action). */
interface Command { id: string; group: string; label: string; icon: ReactNode; to?: string; action?: () => void }

/** True when every character of the query appears in the label in order, so "glr" finds "Global rules". */
function matches(label: string, query: string): boolean {
  let at = 0;
  for (const char of label.toLowerCase()) if (char === query[at]) at += 1;
  return at === query.length;
}

/** Lower is better: a label that starts with the query beats one that only contains it, which beats a scattered match. */
function rank(label: string, query: string): number {
  const lower = label.toLowerCase();
  return lower.startsWith(query) ? 0 : lower.includes(query) ? 1 : 2;
}

/** Groups keep the order in which their first command appears, so the best match's group comes first. */
function groupBy(commands: Command[]): { name: string; items: Command[] }[] {
  const groups = new Map<string, Command[]>();
  for (const command of commands) groups.set(command.group, [...(groups.get(command.group) ?? []), command]);
  return [...groups].map(([name, items]) => ({ name, items }));
}

/**
 * Ctrl+K: one box to jump to any page or project, or to search the workspace.
 * It is a modal listbox (combobox pattern): arrows move, Enter opens, Escape closes.
 */
export function CommandPalette({ projects, current, onClose }: { projects: Project[]; current?: Project; onClose: () => void }) {
  const dialogRef = useModalDialog();
  const navigate = useNavigate();
  const listId = useId();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const q = query.trim().toLowerCase();

  const groups = useMemo(() => {
    const all: Command[] = [];
    if (current) {
      for (const section of projectSections) all.push({ id: `section-${section.path}`, group: current.name, label: section.label, icon: <ArrowRight size={16} aria-hidden="true" />, to: projectPath(current.id, section.path) });
    }
    for (const item of [...primaryNav, projectsNavItem, ...secondaryNav, ...supportNav]) {
      const Icon = item.icon;
      all.push({ id: `page-${item.to}`, group: t("Go to"), label: item.label, icon: <Icon size={16} aria-hidden="true" />, to: item.to });
    }
    for (const project of projects) all.push({ id: `project-${project.id}`, group: t("Projects"), label: project.name, icon: <ProjectAvatar project={project} size="small" />, to: projectPath(project.id) });
    all.push({ id: "new-project", group: t("Create"), label: t("New project"), icon: <Plus size={16} aria-hidden="true" />, to: "/projects?new=1" });
    for (const { value, label, icon: Icon } of themeChoices) {
      all.push({ id: `theme-${value}`, group: t("Appearance"), label: t("{name} theme", { name: t(label) }), icon: <Icon size={16} aria-hidden="true" />, action: () => setTheme(value) });
    }

    const found = q ? all.filter((c) => matches(c.label, q)).sort((a, b) => rank(a.label, q) - rank(b.label, q)) : all;
    if (!q) return groupBy(found);
    // Typing always offers a full search. It comes after pages and projects whose name contains the text,
    // so "soul" + Enter opens Starling, but before loose letter-by-letter matches, so a phrase never dead-ends.
    const search: Command[] = [];
    const encoded = encodeURIComponent(query.trim());
    if (current) search.push({ id: "search-here", group: t("Search"), label: t("Search \"{query}\" in {name}", { query: query.trim(), name: current.name }), icon: <Search size={16} aria-hidden="true" />, to: `/search?q=${encoded}&project=${encodeURIComponent(current.id)}` });
    search.push({ id: "search-all", group: t("Search"), label: t("Search \"{query}\" in all projects", { query: query.trim() }), icon: <FileSearch size={16} aria-hidden="true" />, to: `/search?q=${encoded}` });
    const close = found.filter((c) => rank(c.label, q) < 2);
    const loose = found.filter((c) => rank(c.label, q) === 2);
    return groupBy([...close, ...search, ...loose]);
  }, [current, projects, q, query]);
  // Keyboard order is display order: group by group, best match first within each.
  const commands = groups.flatMap((group) => group.items);

  const selected = Math.min(active, Math.max(commands.length - 1, 0));

  function run(command: Command | undefined) {
    if (!command) return;
    onClose();
    if (command.action) command.action();
    else if (command.to) navigate(command.to);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((selected + step + commands.length) % Math.max(commands.length, 1));
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      setActive(event.key === "Home" ? 0 : commands.length - 1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      run(commands[selected]);
    }
  }

  const optionId = (index: number) => `${listId}-option-${index}`;

  return (
    <dialog
      ref={dialogRef}
      aria-label={t("Search or jump to")}
      onCancel={(event) => { event.preventDefault(); onClose(); }}
      onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}
      className="dialog-panel mx-auto mt-[12vh] w-[calc(100%-2rem)] max-w-xl overflow-hidden rounded-xl border border-line bg-surface p-0 text-ink shadow-dialog backdrop:bg-black/40"
    >
      <div className="flex items-center gap-3 border-b border-line px-4">
        <Search size={18} className="flex-none text-ink-subtle" aria-hidden="true" />
        <input
          autoFocus
          role="combobox"
          aria-expanded="true"
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={commands.length ? optionId(selected) : undefined}
          aria-label={t("Search or jump to")}
          placeholder={t("Search or jump to…")}
          value={query}
          maxLength={200}
          onChange={(event) => { setQuery(event.target.value); setActive(0); }}
          onKeyDown={onKeyDown}
          className="h-13 min-w-0 flex-1 bg-transparent text-base text-ink outline-none placeholder:text-ink-subtle"
        />
        <kbd className="flex-none rounded border border-line px-1.5 text-xs text-ink-subtle">Esc</kbd>
      </div>
      <div id={listId} role="listbox" aria-label={t("Results")} className="max-h-[min(60vh,420px)] overflow-y-auto p-2">
        {groups.map((group) => (
          <div key={group.name} role="group" aria-label={group.name} className="pb-1">
            <div className="px-2.5 pb-1 pt-2 text-xs font-semibold uppercase tracking-wider text-ink-subtle" aria-hidden="true">{group.name}</div>
            {group.items.map((command) => { const index = commands.indexOf(command); return (
              <div
                key={command.id}
                id={optionId(index)}
                role="option"
                aria-selected={index === selected}
                onMouseMove={() => { if (index !== selected) setActive(index); }}
                onClick={() => run(command)}
                className={`flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2 text-sm ${index === selected ? "bg-sage-pale text-ink" : "text-ink-muted"}`}
              >
                <span className={`flex h-6 w-6 flex-none items-center justify-center ${index === selected ? "text-forest" : "text-ink-subtle"}`}>{command.icon}</span>
                <span className="min-w-0 flex-1 truncate">{command.label}</span>
                {index === selected && <CornerDownLeft size={14} className="flex-none text-ink-subtle" aria-hidden="true" />}
              </div>
            ); })}
          </div>
        ))}
        {!commands.length && <p className="px-3 py-6 text-center text-sm text-ink-muted">{t("Nothing matches.")}</p>}
      </div>
    </dialog>
  );
}

import { ChevronDown, ChevronRight, FileText, Folder, GitCommitHorizontal } from "lucide-react";
import { useMemo, useState } from "react";
import type { FileTreeEntry } from "../../types/files";
import { t } from "../../lib/i18n";

interface Node { name: string; path: string; children: Map<string, Node>; entry?: FileTreeEntry }

function build(entries: FileTreeEntry[]): Node {
  const root: Node = { name: "", path: "", children: new Map() };
  for (const entry of entries) {
    let node = root;
    entry.path.split("/").forEach((part, index, parts) => {
      const path = parts.slice(0, index + 1).join("/");
      if (!node.children.has(part)) node.children.set(part, { name: part, path, children: new Map() });
      node = node.children.get(part)!;
      if (index === parts.length - 1) node.entry = entry;
    });
  }
  return root;
}

/** Folders that hold a changed or annotated file open by default, so nothing important hides. */
function interesting(entries: FileTreeEntry[]): Set<string> {
  const open = new Set<string>();
  for (const e of entries) {
    if (!e.has_notes && !e.changed) continue;
    const parts = e.path.split("/");
    for (let i = 1; i < parts.length; i++) open.add(parts.slice(0, i).join("/"));
  }
  return open;
}

function Row({ node, depth, open, toggle, selected, onSelect }: { node: Node; depth: number; open: Set<string>; toggle: (path: string) => void; selected: string | null; onSelect: (path: string) => void }) {
  const isDir = !node.entry || node.children.size > 0;
  const expanded = open.has(node.path);
  const pad = { paddingLeft: `${depth * 14 + 8}px` };
  if (isDir) {
    return (
      <li>
        <button type="button" onClick={() => toggle(node.path)} aria-expanded={expanded} style={pad} className="flex w-full items-center gap-1.5 rounded-lg py-1.5 pr-2 text-left text-sm text-ink hover:bg-sage-pale focus-visible:outline-2 focus-visible:outline-forest">
          {expanded ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}<Folder size={15} className="text-ink-subtle" aria-hidden="true" /><span className="truncate">{node.name}</span>
        </button>
        {expanded && <ul>{[...node.children.values()].sort(sortNodes).map((c) => <Row key={c.path} node={c} depth={depth + 1} open={open} toggle={toggle} selected={selected} onSelect={onSelect} />)}</ul>}
      </li>
    );
  }
  const e = node.entry!;
  return (
    <li>
      <button type="button" onClick={() => onSelect(e.path)} aria-current={selected === e.path ? "true" : undefined} style={pad} className={`flex w-full items-center gap-1.5 rounded-lg py-1.5 pr-2 text-left text-sm focus-visible:outline-2 focus-visible:outline-forest ${selected === e.path ? "bg-sage-pale font-semibold text-forest" : "text-ink hover:bg-sage-pale"}`}>
        <span className="w-[14px]" /><FileText size={15} className="shrink-0 text-ink-subtle" aria-hidden="true" /><span className="min-w-0 flex-1 truncate">{node.name}</span>
        {e.has_notes && <span className="rounded bg-sage-pale px-1.5 text-xs font-semibold text-forest" title={t("Has notes")}>{t("Notes")}</span>}
        {e.stale && <span className="rounded bg-warning-soft px-1.5 text-xs font-semibold text-warning-ink" title={t("Changed since you last reviewed it")}>{t("Changed since review")}</span>}
        {e.changed && <span className="inline-flex items-center gap-0.5 rounded bg-info-soft px-1.5 text-xs font-semibold text-info-ink" title={t("{state} in the working tree", { state: e.changed })}><GitCommitHorizontal size={11} aria-hidden="true" />{e.changed}</span>}
      </button>
    </li>
  );
}

const sortNodes = (a: Node, b: Node) => Number(b.children.size > 0) - Number(a.children.size > 0) || a.name.localeCompare(b.name);

export function FileTreeView({ entries, selected, onSelect, filter }: { entries: FileTreeEntry[]; selected: string | null; onSelect: (path: string) => void; filter: string }) {
  const visible = useMemo(() => { const f = filter.trim().toLowerCase(); return f ? entries.filter((e) => e.path.toLowerCase().includes(f)) : entries; }, [entries, filter]);
  const root = useMemo(() => build(visible), [visible]);
  const [manual, setManual] = useState<Record<string, boolean>>({});
  const auto = useMemo(() => (filter.trim() ? new Set(visible.flatMap((e) => e.path.split("/").slice(0, -1).map((_, i, a) => a.slice(0, i + 1).join("/")))) : interesting(entries)), [filter, visible, entries]);
  const open = useMemo(() => { const set = new Set(auto); for (const [path, value] of Object.entries(manual)) { if (value) set.add(path); else set.delete(path); } set.add(""); return set; }, [auto, manual]);
  const toggle = (path: string) => setManual((m) => ({ ...m, [path]: !open.has(path) }));
  if (!visible.length) return <p className="px-2 py-6 text-center text-sm text-ink-subtle">{filter ? t("No files match.") : t("No files to show.")}</p>;
  return <ul aria-label={t("Repository files")}>{[...root.children.values()].sort(sortNodes).map((c) => <Row key={c.path} node={c} depth={0} open={open} toggle={toggle} selected={selected} onSelect={onSelect} />)}</ul>;
}

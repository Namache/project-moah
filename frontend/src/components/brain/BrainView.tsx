import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { Brain } from "lucide-react";
import { HelpTip } from "../ui";
import { TypedLinks } from "../links/TypedLinks";
import { useBrainActivation, useWorkspaceBrain } from "../../hooks/useGraph";
import { useWorkspaceTasks } from "../../hooks/useTasks";
import { buildBrainLayout } from "./layout";
import { useBrainStore } from "./store";
import { KIND_COLORS } from "./colors";
import type { BrainActivation, BrainGraph, BrainShelf, NodeKind, WorkspaceBrain } from "../../types/graph";
import { labels, msg, t } from "../../lib/i18n";

// The 3D scene and its libraries load only when someone opens the Brain page.
const BrainScene = lazy(() => import("./BrainScene").then((m) => ({ default: m.BrainScene })));

function hasWebGL(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

const KINDS: { kind: NodeKind; label: string }[] = [
  labels({ kind: "task", label: msg("Tasks") }, ["label"]),
  labels({ kind: "memory", label: msg("Memory") }, ["label"]),
  labels({ kind: "file", label: msg("Files") }, ["label"]),
  labels({ kind: "milestone", label: msg("Milestones") }, ["label"]),
];

/**
 * Turns the workspace payload into one graph. The shared tree's topics are regions of their own,
 * since every project files on them; a project's region holds its own shelves and whatever sits
 * on no shelf. Global rules sit in the middle.
 */
export function workspaceGraph(brain: WorkspaceBrain): BrainGraph {
  const shelves: BrainShelf[] = [
    ...brain.projects.map((p) => ({ id: projectRegion(p.id), name: p.name, parent_id: null, core: p.global })),
    ...brain.shelves.map((s) => ({ id: s.id, name: s.name, parent_id: s.parent_id ?? (s.shared ? null : projectRegion(s.project_id)), shared: s.shared })),
  ];
  const known = new Set(shelves.map((s) => s.id));
  const nodes = brain.nodes.map((n) => {
    const own = n.shelves.filter((id) => known.has(id));
    return { ...n, shelves: own.length ? own : [projectRegion(n.project_id)] };
  });
  return { nodes, links: brain.links, shelves };
}
const projectRegion = (projectId: string) => `project:${projectId}`;

/** Brain View (design sections 75 to 82): the whole workspace's knowledge drawn as one living brain. */
export function BrainView({ webgl = hasWebGL() }: { webgl?: boolean }) {
  const brain = useWorkspaceBrain();
  const tasks = useWorkspaceTasks();
  const [task, setTask] = useState<{ project: string; ref: string } | null>(null);
  const activation = useBrainActivation(task?.project ?? null, task?.ref ?? null);
  const { selected, hovered, focusShelf, showGuesses, select, setFocusShelf, setShowGuesses } = useBrainStore();
  const [find, setFind] = useState("");
  const data = useMemo(() => (brain.data ? workspaceGraph(brain.data) : undefined), [brain.data]);
  const layout = useMemo(() => (data ? buildBrainLayout(data) : null), [data]);
  const byKey = useMemo(() => new Map((brain.data?.nodes ?? []).map((n) => [n.key, n])), [brain.data]);
  const projects = brain.data?.projects ?? [];
  const projectNames = new Map(projects.map((p) => [p.id, p.name]));
  const openTasks = (tasks.data ?? []).filter((t) => t.status !== "completed" && t.status !== "archived" && projectNames.has(t.project_id));

  useEffect(() => () => { select(null); setFocusShelf(null); }, [select, setFocusShelf]);

  function findRecord(value: string) {
    setFind(value);
    const wanted = value.trim().toLowerCase();
    const hit = brain.data?.nodes.find((n) => n.label.toLowerCase() === wanted || `${n.label} ${n.title}`.toLowerCase() === wanted);
    if (hit) select(hit.key);
  }

  if (brain.isError) return <p role="alert" className="text-sm text-danger-ink">{t("The brain could not be loaded:")} {brain.error.message}</p>;
  const shelfNames = new Map((data?.shelves ?? []).map((s) => [s.id, s.name]));
  // The task's own project region wakes too, so you can see where the work lives.
  const lit: BrainActivation | null = activation.data && task ? { ...activation.data, shelves: { ...activation.data.shelves, [projectRegion(task.project)]: 0.6 } } : null;
  const focusProject = focusShelf?.startsWith("project:") ? focusShelf.slice(8) : (brain.data?.shelves.find((s) => s.id === focusShelf)?.project_id ?? null);
  const shelfChips = (brain.data?.shelves ?? []).filter((s) => s.project_id === focusProject || (lit?.shelves[s.id] ?? 0) > 0);
  const chip = (id: string, name: string) => {
    const awake = lit?.shelves[id];
    return <li key={id}><button type="button" aria-pressed={focusShelf === id} onClick={() => setFocusShelf(focusShelf === id ? null : id)} className={`rounded-full border px-2.5 py-0.5 text-xs ${focusShelf === id ? "border-forest bg-sage-pale font-semibold text-forest" : awake ? "border-forest text-forest" : "border-line text-ink-muted"}`}>{name}{awake ? ` ${Math.round(awake * 100)}%` : ""}</button></li>;
  };

  return (
    <div>
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-0 flex-1">
          <label htmlFor="brain-task" className="text-xs font-semibold text-ink-muted">{t("Light up a task")}</label>
          <select id="brain-task" className="field-input mt-1" value={task ? `${task.project}|${task.ref}` : ""} onChange={(e) => { const [project, ref] = e.target.value.split("|"); setTask(ref ? { project, ref } : null); }}>
            <option value="">{t("No task: show everything")}</option>
            {projects.map((p) => {
              const own = openTasks.filter((t) => t.project_id === p.id);
              return own.length ? <optgroup key={p.id} label={p.name}>{own.map((t) => <option key={t.id} value={`${p.id}|${t.human_id}`}>{t.human_id} {t.title}</option>)}</optgroup> : null;
            })}
          </select>
        </div>
        <div className="min-w-0 flex-1">
          <label htmlFor="brain-find" className="text-xs font-semibold text-ink-muted">{t("Find a record")}</label>
          <input id="brain-find" list="brain-records" className="field-input mt-1" value={find} onChange={(e) => findRecord(e.target.value)} placeholder={t("DEC-003, PB-12…")} />
          <datalist id="brain-records">{(brain.data?.nodes ?? []).slice(0, 3000).map((n) => <option key={n.key} value={n.label}>{projectNames.get(n.project_id)}: {n.title}</option>)}</datalist>
        </div>
        <label className="flex items-center gap-2 pb-2 text-xs text-ink-muted"><input type="checkbox" checked={showGuesses} onChange={(e) => setShowGuesses(e.target.checked)} />{t("Show guessed links")}</label>
      </div>

      {projects.length > 0 && <ul className="mt-3 flex flex-wrap gap-1.5" aria-label={t("Project regions")}>{projects.map((p) => chip(projectRegion(p.id), p.name))}</ul>}
      {shelfChips.length > 0 && <ul className="mt-1.5 flex flex-wrap gap-1.5" aria-label={t("Shelf regions")}>{shelfChips.map((s) => chip(s.id, s.name))}</ul>}

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="relative h-[36rem] overflow-hidden rounded-xl bg-[#03060d]" aria-label={t("Brain view: {items} items in {projects} projects and {links} links. Drag to turn, scroll to zoom, click a point to inspect it.", { items: brain.data?.nodes.length ?? 0, projects: projects.length, links: brain.data?.links.length ?? 0 })} role="img">
          {!webgl ? <Fallback />
            : data && layout ? <Suspense fallback={<Loading />}><BrainScene data={data} layout={layout} activation={lit} /></Suspense>
            : <Loading />}
          {hovered && byKey.get(hovered) && <div className="pointer-events-none absolute left-3 top-3 max-w-[70%] truncate rounded-lg bg-black/60 px-2.5 py-1 text-xs text-white">{projectNames.get(byKey.get(hovered)!.project_id)} · <strong>{byKey.get(hovered)!.label}</strong> {byKey.get(hovered)!.title}</div>}
          <Legend lit={lit} />
        </div>
        <Inspector node={selected ? byKey.get(selected) ?? null : null} brain={brain.data} lit={lit} byKey={byKey} shelfNames={shelfNames} projectNames={projectNames} onOpen={select} />
      </div>
    </div>
  );
}

function Loading() {
  return <p role="status" className="absolute inset-0 flex items-center justify-center text-sm text-slate-300">{t("Growing the brain…")}</p>;
}

function Fallback() {
  return <p className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-slate-300">{t("This computer could not start 3D graphics (WebGL), so the brain can't be drawn. Links still work from each project's Memory and Tasks tabs.")}</p>;
}

function Legend({ lit }: { lit: BrainActivation | null }) {
  return (
    <div className="pointer-events-none absolute bottom-3 left-3 flex flex-wrap gap-3 text-xs text-slate-300">
      {KINDS.map(({ kind, label }) => <span key={kind} className="flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{ background: KIND_COLORS[kind] }} />{label}</span>)}
      {lit && <span>{t("Working as: {operation}. Bright points made the context pack, sparks show the path that brought them.", { operation: lit.operation })}</span>}
    </div>
  );
}

type WorkspaceNode = WorkspaceBrain["nodes"][number];

function Inspector({ node, brain, lit, byKey, shelfNames, projectNames, onOpen }: {
  node: WorkspaceNode | null; brain?: WorkspaceBrain; lit: BrainActivation | null;
  byKey: Map<string, WorkspaceNode>; shelfNames: Map<string, string>; projectNames: Map<string, string>; onOpen: (key: string) => void;
}) {
  if (!node) {
    return (
      <aside aria-label={t("Inspector")} className="rounded-xl border border-line bg-surface p-4 text-sm text-ink-muted shadow-card">
        <p className="flex items-center gap-2 font-semibold text-ink"><Brain size={17} className="text-forest" aria-hidden="true" />{t("Inspector")}</p>
        <p className="mt-2 text-xs leading-5">{t("Click a point to see what it is, what it links to and which shelves it sits on. Pick a task above to see what its context pack would pull in, and along which links.")}</p>
        {brain && <p className="mt-3 text-xs text-ink-subtle">{t("Items: {items}, links: {links}, projects: {projects}, shelves: {shelves}.", { items: brain.nodes.length, links: brain.links.filter((l) => l.status !== "candidate").length, projects: brain.projects.length, shelves: brain.shelves.length })}</p>}
        <p className="mt-3 flex items-center gap-1.5 text-xs text-ink-subtle">{t("The picture is drawn from your tasks, memory and files; changing it here never changes what agents get.")} <HelpTip label={t("brain view")}>{t("Each topic on your shelves is a region of the brain, shared by every project. Records on no shelf sit in their project's region, and global rules sit in the middle. Records drift toward what they link to. Links never cross projects.")}</HelpTip></p>
      </aside>
    );
  }
  const score = lit?.nodes[node.key];
  const path = lit?.paths.find((p) => p[p.length - 1] === node.key);
  return (
    <aside aria-label={t("Inspector")} className="max-h-[36rem] overflow-y-auto rounded-xl border border-line bg-surface p-4 shadow-card">
      <p className="text-xs uppercase tracking-wide text-ink-subtle">{projectNames.get(node.project_id)} · {node.subtype ?? node.kind}{node.status ? ` · ${node.status}` : ""}</p>
      <h3 className="mt-1 text-sm font-semibold text-ink"><span className="text-forest">{node.label}</span>{node.title !== node.label && <> {node.title}</>}</h3>
      {node.shelves.length > 0 && <p className="mt-2 text-xs text-ink-muted">{t("On {shelves}", { shelves: node.shelves.map((id) => shelfNames.get(id) ?? id).join(", ") })}</p>}
      {lit && <p className="mt-2 text-xs text-ink-muted">
        {lit.included.includes(node.key) ? t("In the context pack") : score ? t("Reached but left out of the pack") : t("Not reached for this task")}
        {score ? ` ${t("(score {score})", { score: score.toFixed(2) })}` : ""}
        {path && <span className="mt-1 block text-ink-subtle">{t("Came by: {path}", { path: path.map((k) => byKey.get(k)?.label ?? k).join(" → ") })}</span>}
      </p>}
      <div className="mt-3"><TypedLinks projectId={node.project_id} node={`${node.kind}:${node.id}`} readonly={false} onOpen={(n) => onOpen(`${n.kind}:${n.id}`)} /></div>
    </aside>
  );
}

import { CheckCircle2, FileText, FolderKanban, ListTodo, Brain, Search } from "lucide-react";
import { Link } from "react-router-dom";
import { useUrlParams } from "../hooks/useUrlParams";
import { Button, EmptyState, ErrorState, PageHeading, ProjectAvatar } from "../components/ui";
import { useProjects } from "../hooks/useProjects";
import { useSearch } from "../hooks/useSearch";
import { memoryTypes } from "../types/memory";
import type { MemoryType } from "../types/memory";

const memoryTypeLabels = Object.fromEntries(memoryTypes.map((t) => [t.value, t.label])) as Record<MemoryType, string>;
import type { SearchEntityType, SearchResult } from "../types/search";
import { checkpointPath, memoryPath, projectPath, taskPath } from "../lib/routes";

const entityLabels: Record<SearchEntityType, string> = { project: "Projects", task: "Tasks", memory: "Memory", checkpoint: "Checkpoints", file: "Files" };
const entityIcons = { project: FolderKanban, task: ListTodo, memory: Brain, checkpoint: CheckCircle2, file: FileText } as const;

function resultHref(r: SearchResult): string {
  if (r.entity_type === "task") return taskPath(r.project_id, r.human_id || r.entity_id);
  if (r.entity_type === "memory") return memoryPath(r.project_id, r.human_id || r.entity_id);
  if (r.entity_type === "file") return projectPath(r.project_id, "files", { file: r.title });
  if (r.entity_type === "checkpoint") return checkpointPath(r.project_id, r.entity_id);
  return projectPath(r.project_id);
}

function Row({ result, showProject, color }: { result: SearchResult; showProject: boolean; color?: { icon: string | null; accent: string | null } }) {
  const Icon = entityIcons[result.entity_type] ?? FileText;
  const kind = result.memory_type ? memoryTypeLabels[result.memory_type as MemoryType] ?? result.memory_type : entityLabels[result.entity_type].replace(/s$/, "");
  return (
    <li>
      <Link to={resultHref(result)} className="block rounded-xl border border-line bg-surface p-4 hover:border-forest/40 hover:shadow-card focus-visible:outline-2 focus-visible:outline-forest">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span className="inline-flex items-center gap-1.5 font-semibold text-forest"><Icon size={14} aria-hidden="true" />{kind}</span>
          {result.human_id && <span className="font-bold tracking-wide text-ink-muted">{result.human_id}</span>}
          <span className="rounded-full bg-neutral-soft px-2 py-0.5 font-semibold capitalize text-ink-muted">{result.status.replace("_", " ")}</span>
          {showProject && <span className="inline-flex items-center gap-1.5 font-semibold text-ink"><ProjectAvatar size="small" project={{ name: result.project_name, icon: color?.icon ?? null, accent: color?.accent ?? null }} />{result.project_name}</span>}
        </div>
        <h2 className="mt-2 text-sm font-semibold text-ink">{result.title}</h2>
        {result.snippet && <p className="mt-1 line-clamp-2 text-sm leading-6 text-ink-muted">{result.snippet}</p>}
      </Link>
    </li>
  );
}

export function SearchPage() {
  const [params, updateParams] = useUrlParams();
  const q = params.get("q") ?? "";
  const projectId = params.get("project");
  const scopeAll = params.get("scope") === "all" || !projectId;
  const entity = (params.get("type") as SearchEntityType | null) ?? null;
  const memoryType = (params.get("memory_type") as MemoryType | null) ?? null;
  const history = params.get("history") === "1";
  const projects = useProjects();
  const scopeProject = projects.data?.find((p) => p.id === projectId);
  const style = new Map((projects.data ?? []).map((p) => [p.id, { icon: p.icon, accent: p.accent }]));

  const set = (key: string, value: string | null) => updateParams({ [key]: value });
  const query = useSearch(scopeAll ? null : projectId, { q, entityTypes: entity ? [entity] : undefined, memoryTypes: memoryType ? [memoryType] : undefined, includeArchived: history });
  const types: (SearchEntityType | null)[] = [null, "task", "memory", "checkpoint", "file", ...(scopeAll ? ["project" as const] : [])];

  return (
    <div>
      <PageHeading title="Search" />
      <form role="search" aria-label="Search query" className="mt-6 flex gap-2" onSubmit={(e) => { e.preventDefault(); set("q", String(new FormData(e.currentTarget).get("q") ?? "").trim() || null); }}>
        <input key={q} name="q" defaultValue={q} aria-label="Search words" placeholder="Search tasks, memory, and checkpoints" className="field-input" maxLength={200} autoFocus />
        <Button type="submit" variant="primary"><Search size={16} aria-hidden="true" />Search</Button>
      </form>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        {projectId && (
          <div role="group" aria-label="Search scope" className="segmented">
            <button type="button" aria-pressed={!scopeAll} onClick={() => set("scope", null)} className={`filter-tab ${!scopeAll ? "filter-tab-active" : ""}`}>{scopeProject ? `In ${scopeProject.name}` : "This project"}</button>
            <button type="button" aria-pressed={scopeAll} onClick={() => set("scope", "all")} className={`filter-tab ${scopeAll ? "filter-tab-active" : ""}`}>All projects</button>
          </div>
        )}
        <div role="group" aria-label="Result type" className="segmented">
          {types.map((t) => <button key={t ?? "all"} type="button" aria-pressed={entity === t} onClick={() => updateParams(t === "memory" ? { type: t } : { type: t, memory_type: null })} className={`filter-tab ${entity === t ? "filter-tab-active" : ""}`}>{t ? entityLabels[t] : "All"}</button>)}
        </div>
        {(entity === "memory" || memoryType) && (
          <select aria-label="Memory type" value={memoryType ?? ""} onChange={(e) => updateParams(e.target.value ? { memory_type: e.target.value, type: "memory" } : { memory_type: null })} className="field-input !min-h-10 !w-auto">
            <option value="">Any memory type</option>
            {memoryTypes.map((m) => <option key={m.value} value={m.value}>{m.plural}</option>)}
          </select>
        )}
        <label className="inline-flex items-center gap-2 text-sm text-ink-muted"><input type="checkbox" checked={history} onChange={(e) => set("history", e.target.checked ? "1" : null)} className="h-4 w-4 accent-primary" />Include archived and history</label>
      </div>
      {scopeAll && <p className="mt-3 text-xs text-ink-subtle">Searching every active project. Results show which project they belong to, and are never sent to an agent automatically.</p>}

      <div className="mt-6" aria-live="polite">
        {!q.trim() ? <EmptyState icon={<Search size={26} />} title="What are you looking for?">Search by words, or by an ID such as CAMP-037. Press / anywhere to jump here.</EmptyState>
          : query.isPending ? <div role="status" aria-label="Searching" className="h-40 animate-pulse rounded-xl bg-surface" />
          : query.isError ? <ErrorState title="Search could not run" message={query.error.message} onRetry={() => void query.refetch()} />
          : query.data.items.length === 0 ? <EmptyState icon={<Search size={26} />} title={`No results for "${q.trim()}"`}>{!scopeAll ? "Try searching all projects, " : "Try different words, "}{history ? "or check the spelling." : "or turn on archived and history."}</EmptyState>
          : <>
            <p className="mb-3 text-sm text-ink-muted">{query.data.total} {query.data.total === 1 ? "result" : "results"}</p>
            <ul className="space-y-2.5">{query.data.items.map((r) => <Row key={`${r.entity_type}:${r.entity_id}`} result={r} showProject={scopeAll} color={style.get(r.project_id)} />)}</ul>
            {query.hasNextPage && <div className="mt-5 text-center"><Button onClick={() => void query.fetchNextPage()} disabled={query.isFetchingNextPage}>{query.isFetchingNextPage ? "Loading…" : "Load more"}</Button></div>}
          </>}
      </div>
    </div>
  );
}

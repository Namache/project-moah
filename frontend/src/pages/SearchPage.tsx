import { CheckCircle2, FileText, FolderKanban, ListTodo, Brain, Search } from "lucide-react";
import { Link } from "react-router-dom";
import { useUrlParams } from "../hooks/useUrlParams";
import { Button, EmptyState, ErrorState, PageHeading, ProjectAvatar } from "../components/ui";
import { useProjects } from "../hooks/useProjects";
import { useSearch } from "../hooks/useSearch";
import { memoryTypes } from "../types/memory";
import type { MemoryType } from "../types/memory";
import { statusLabels, type TaskStatus } from "../types/task";
import type { SearchEntityType, SearchResult } from "../types/search";
import { checkpointPath, memoryPath, projectPath, taskPath } from "../lib/routes";
import { labels, msg, t, tp } from "../lib/i18n";

const entityLabels: Record<SearchEntityType, string> = labels({ project: msg("Projects"), task: msg("Tasks"), memory: msg("Memory"), checkpoint: msg("Checkpoints"), file: msg("Files") });
const entityKinds: Record<SearchEntityType, string> = labels({ project: msg("Project"), task: msg("Task"), memory: msg("Memory"), checkpoint: msg("Checkpoint"), file: msg("File") });
/** Statuses of memory, projects and the rest; tasks use their board column names. */
const otherStatuses: Record<string, string> = labels({ active: msg("Active"), paused: msg("Paused"), completed: msg("Completed"), archived: msg("Archived"), superseded: msg("Superseded"), invalidated: msg("Invalidated") });

function statusText(r: SearchResult): string {
  const known = r.entity_type === "task" ? statusLabels[r.status as TaskStatus] : otherStatuses[r.status];
  return known ?? r.status.replace("_", " ");
}
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
  const kind = result.memory_type ? memoryTypes.find((m) => m.value === (result.memory_type as MemoryType))?.label ?? result.memory_type : entityKinds[result.entity_type];
  return (
    <li>
      <Link to={resultHref(result)} className="block rounded-xl border border-line bg-surface p-4 hover:border-forest/40 hover:shadow-card focus-visible:outline-2 focus-visible:outline-forest">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span className="inline-flex items-center gap-1.5 font-semibold text-forest"><Icon size={14} aria-hidden="true" />{kind}</span>
          {result.human_id && <span className="font-bold tracking-wide text-ink-muted">{result.human_id}</span>}
          <span className="rounded-full bg-neutral-soft px-2 py-0.5 font-semibold text-ink-muted">{statusText(result)}</span>
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
      <PageHeading title={t("Search")} />
      <form role="search" aria-label={t("Search query")} className="mt-6 flex gap-2" onSubmit={(e) => { e.preventDefault(); set("q", String(new FormData(e.currentTarget).get("q") ?? "").trim() || null); }}>
        <input key={q} name="q" defaultValue={q} aria-label={t("Search words")} placeholder={t("Search tasks, memory, and checkpoints")} className="field-input" maxLength={200} autoFocus />
        <Button type="submit" variant="primary"><Search size={16} aria-hidden="true" />{t("Search")}</Button>
      </form>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        {projectId && (
          <div role="group" aria-label={t("Search scope")} className="segmented">
            <button type="button" aria-pressed={!scopeAll} onClick={() => set("scope", null)} className={`filter-tab ${!scopeAll ? "filter-tab-active" : ""}`}>{scopeProject ? t("In {name}", { name: scopeProject.name }) : t("This project")}</button>
            <button type="button" aria-pressed={scopeAll} onClick={() => set("scope", "all")} className={`filter-tab ${scopeAll ? "filter-tab-active" : ""}`}>{t("All projects")}</button>
          </div>
        )}
        <div role="group" aria-label={t("Result type")} className="segmented">
          {types.map((kind) => <button key={kind ?? "all"} type="button" aria-pressed={entity === kind} onClick={() => updateParams(kind === "memory" ? { type: kind } : { type: kind, memory_type: null })} className={`filter-tab ${entity === kind ? "filter-tab-active" : ""}`}>{kind ? entityLabels[kind] : t("All")}</button>)}
        </div>
        {(entity === "memory" || memoryType) && (
          <select aria-label={t("Memory type")} value={memoryType ?? ""} onChange={(e) => updateParams(e.target.value ? { memory_type: e.target.value, type: "memory" } : { memory_type: null })} className="field-input !min-h-10 !w-auto">
            <option value="">{t("Any memory type")}</option>
            {memoryTypes.map((m) => <option key={m.value} value={m.value}>{m.plural}</option>)}
          </select>
        )}
        <label className="inline-flex items-center gap-2 text-sm text-ink-muted"><input type="checkbox" checked={history} onChange={(e) => set("history", e.target.checked ? "1" : null)} className="h-4 w-4 accent-primary" />{t("Include archived and history")}</label>
      </div>
      {scopeAll && <p className="mt-3 text-xs text-ink-subtle">{t("Searching every active project. Results show which project they belong to, and are never sent to an agent automatically.")}</p>}

      <div className="mt-6" aria-live="polite">
        {!q.trim() ? <EmptyState icon={<Search size={26} />} title={t("What are you looking for?")}>{t("Search by words, or by an ID such as CAMP-037. Press / anywhere to jump here.")}</EmptyState>
          : query.isPending ? <div role="status" aria-label={t("Searching")} className="h-40 animate-pulse rounded-xl bg-surface" />
          : query.isError ? <ErrorState title={t("Search could not run")} message={query.error.message} onRetry={() => void query.refetch()} />
          : query.data.items.length === 0 ? <EmptyState icon={<Search size={26} />} title={t("No results for \"{query}\"", { query: q.trim() })}>{!scopeAll ? (history ? t("Try searching all projects, or check the spelling.") : t("Try searching all projects, or turn on archived and history.")) : (history ? t("Try different words, or check the spelling.") : t("Try different words, or turn on archived and history."))}</EmptyState>
          : <>
            <p className="mb-3 text-sm text-ink-muted">{tp(query.data.total, "{count} result", "{count} results")}</p>
            <ul className="space-y-2.5">{query.data.items.map((r) => <Row key={`${r.entity_type}:${r.entity_id}`} result={r} showProject={scopeAll} color={style.get(r.project_id)} />)}</ul>
            {query.hasNextPage && <div className="mt-5 text-center"><Button onClick={() => void query.fetchNextPage()} disabled={query.isFetchingNextPage}>{query.isFetchingNextPage ? t("Loading…") : t("Load more")}</Button></div>}
          </>}
      </div>
    </div>
  );
}

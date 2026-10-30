import { useMemo, useState } from "react";
import { BookOpen, ChevronDown, Layers, Plus, Search, SlidersHorizontal } from "lucide-react";
import { Link } from "react-router-dom";
import { useUrlParams } from "../hooks/useUrlParams";
import { IssueReview } from "../components/memory/IssueReview";
import { MemoryCard } from "../components/memory/MemoryCard";
import { MemoryPanel } from "../components/memory/MemoryPanel";
import { LinkReview } from "../components/links/LinkReview";
import { ShelvesPanel } from "../components/links/ShelvesPanel";
import { Button, EmptyState, ErrorState, SegmentedControl, buttonBase, buttonClasses, collapsiblePill } from "../components/ui";
import { memoryTypeStyle } from "../lib/tones";
import { useMemoryCounts, useMemoryFeed } from "../hooks/useMemory";
import type { AiVisibility, MemoryFilters, MemorySort, MemoryStatus, MemoryType } from "../types/memory";
import { memoryTypes, visibilityLabels } from "../types/memory";

type TriState = "all" | "yes" | "no";
type StatusFilter = MemoryStatus | "all";
type IssueFilter = "all" | "pending" | "resolved";

const allStatuses: MemoryStatus[] = ["active", "archived", "superseded", "invalidated"];
const sortOptions: { value: MemorySort; label: string }[] = [
  { value: "priority", label: "Priority first" },
  { value: "updated_desc", label: "Recently updated" },
  { value: "updated_asc", label: "Oldest updated" },
  { value: "title_asc", label: "Title A–Z" },
];

function flag(value: TriState): boolean | undefined {
  return value === "all" ? undefined : value === "yes";
}

export function MemoryPage({ projectId, archived }: { projectId: string; archived: boolean }) {
  const [params, updateParams] = useUrlParams();
  const selected = params.get("memory");
  const creating = params.get("new") === "1";
  const taskRef = params.get("task");
  const newType = memoryTypes.find((t) => t.value === params.get("type"))?.value;
  const [category, setCategory] = useState<MemoryType | "all">("all");
  const [search, setSearch] = useState("");
  const [tag, setTag] = useState("");
  const [status, setStatus] = useState<StatusFilter>("active");
  const [visibility, setVisibility] = useState<AiVisibility | "all">("all");
  const [pinned, setPinned] = useState<TriState>("all");
  const [locked, setLocked] = useState<TriState>("all");
  const [reviewing, setReviewing] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const [issueState, setIssueState] = useState<IssueFilter>("all");
  const [sort, setSort] = useState<MemorySort>("priority");

  const filters = useMemo<MemoryFilters>(() => ({
    types: category === "all" ? undefined : [category],
    statuses: status === "all" ? allStatuses : [status],
    visibility: visibility === "all" ? undefined : [visibility],
    pinned: flag(pinned),
    locked: flag(locked),
    resolved: category === "bug" && issueState !== "all" ? issueState === "resolved" : undefined,
    tag: tag.trim() || undefined,
    task: taskRef || undefined,
    q: search.trim() || undefined,
    sort,
  }), [category, status, visibility, pinned, locked, issueState, tag, taskRef, search, sort]);
  const feed = useMemoryFeed(projectId, filters);
  const counts = useMemoryCounts(projectId);
  const records = feed.data?.pages.flat() ?? [];
  const showCounts = status === "active" && Boolean(counts.data);
  const activeCount = Object.values(counts.data?.by_type ?? {}).reduce((sum, value) => sum + (value ?? 0), 0);
  const advancedFilterCount = [status !== "active", visibility !== "all", pinned !== "all", locked !== "all", tag.trim() !== ""].filter(Boolean).length;
  const hasFilters = category !== "all" || search.trim() !== "" || tag.trim() !== "" || status !== "active" || visibility !== "all" || pinned !== "all" || locked !== "all" || Boolean(taskRef);

  const setParam = (key: string, value: string | null) => updateParams({ [key]: value });
  const closePanel = () => updateParams({ memory: null, new: null, type: null });
  const memoryChanged = (ref: string | null) => updateParams({ new: null, type: null, memory: ref });
  const clearFilters = () => {
    setCategory("all"); setSearch(""); setTag(""); setStatus("active"); setVisibility("all"); setPinned("all"); setLocked("all"); setIssueState("all"); setSort("priority");
    setParam("task", null);
  };

  return (
    <div>
      {/* The tab or page title already says where you are, so the heading is for screen readers only. */}
      <h2 className="sr-only">Memory</h2>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SegmentedControl label="Memory categories" value={category} onChange={setCategory} className="min-w-0"
          options={[{ value: "all" as const, label: "All", count: showCounts ? activeCount : undefined }, ...memoryTypes.map((item) => ({ value: item.value, label: item.plural, icon: memoryTypeStyle[item.value].icon, count: showCounts ? counts.data?.by_type[item.value] ?? 0 : undefined }))]} />
        {!archived && <Button variant="primary" onClick={() => setParam("new", "1")}><Plus size={16} aria-hidden="true" />New memory</Button>}
      </div>

      {taskRef && <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-info/40 bg-info-soft px-4 py-2 text-sm text-info-ink"><span>Showing memory linked to <strong>{taskRef}</strong>.</span><button type="button" className="font-semibold underline focus-visible:outline-2 focus-visible:outline-info-ink" onClick={() => setParam("task", null)}>Show all memory</button></div>}

      {counts.isError && <div role="alert" className="mt-3 text-sm text-danger-ink">Memory counts could not be loaded. <button type="button" onClick={() => void counts.refetch()} className="font-semibold underline">Try again</button></div>}

      {category === "bug" && <div className="mt-3 flex flex-wrap items-center gap-3">
      <SegmentedControl label="Known issue state" value={issueState} onChange={setIssueState} options={[{ value: "all", label: "All" }, { value: "pending", label: "Pending" }, { value: "resolved", label: "Resolved" }]} />
      {!archived && <Button onClick={() => setReviewing(true)}><Layers size={16} aria-hidden="true" />Check pending issues</Button>}
      </div>}

      {/* One toolbar: search, sort and filters, then Shelves and Guessed links, which open into full-width panels below it. */}
      <section aria-label="Memory search and filters" className="mt-3 flex flex-wrap items-center gap-2">
        <label className="relative block min-w-56 flex-1"><span className="sr-only">Search memory</span><Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-subtle" aria-hidden="true" /><input type="search" value={search} onChange={(event) => setSearch(event.target.value)} aria-label="Search memory" placeholder="Search titles, content, or IDs" maxLength={200} className="field-input !pl-9" /></label>
        <label className="block w-44"><span className="sr-only">Sort memory</span><select aria-label="Sort memory" value={sort} onChange={(event) => setSort(event.target.value as MemorySort)} className="field-input">{sortOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
        <button type="button" aria-expanded={showFilters} aria-controls="memory-filters" onClick={() => setShowFilters((open) => !open)} className={collapsiblePill}>
          <SlidersHorizontal size={15} className="text-forest" aria-hidden="true" />Filters
          {advancedFilterCount > 0 && <span className="rounded-full bg-primary px-1.5 text-xs font-semibold leading-5 text-white" aria-label={`${advancedFilterCount} active`}>{advancedFilterCount}</span>}
          <ChevronDown size={14} className={`transition-transform ${showFilters ? "rotate-180" : ""}`} aria-hidden="true" />
        </button>
        <ShelvesPanel projectId={projectId} readonly={archived} />
        <LinkReview projectId={projectId} readonly={archived} defaultOpen={params.get("review") === "links"} />
        {hasFilters && <button type="button" onClick={clearFilters} className="px-1 text-sm font-medium text-forest underline focus-visible:outline-2 focus-visible:outline-forest">Clear filters</button>}
        {showFilters && <div id="memory-filters" className="order-last grid basis-full gap-3 rounded-xl border border-line bg-surface p-4 shadow-card sm:grid-cols-2 xl:grid-cols-5">
          <label className="text-xs font-semibold text-ink-muted">Status<select aria-label="Memory status" value={status} onChange={(event) => setStatus(event.target.value as StatusFilter)} className="field-input mt-1"><option value="active">Active</option><option value="all">All statuses</option><option value="archived">Archived</option><option value="superseded">Superseded</option><option value="invalidated">Invalidated</option></select></label>
          <label className="text-xs font-semibold text-ink-muted">AI visibility<select aria-label="AI visibility filter" value={visibility} onChange={(event) => setVisibility(event.target.value as AiVisibility | "all")} className="field-input mt-1"><option value="all">Any visibility</option>{(Object.keys(visibilityLabels) as AiVisibility[]).map((value) => <option key={value} value={value}>{visibilityLabels[value]}</option>)}</select></label>
          <label className="text-xs font-semibold text-ink-muted">Pinned<select aria-label="Pinned filter" value={pinned} onChange={(event) => setPinned(event.target.value as TriState)} className="field-input mt-1"><option value="all">Any</option><option value="yes">Pinned{counts.data ? ` (${counts.data.pinned})` : ""}</option><option value="no">Not pinned</option></select></label>
          <label className="text-xs font-semibold text-ink-muted">Locked<select aria-label="Locked filter" value={locked} onChange={(event) => setLocked(event.target.value as TriState)} className="field-input mt-1"><option value="all">Any</option><option value="yes">Locked{counts.data ? ` (${counts.data.locked})` : ""}</option><option value="no">Unlocked</option></select></label>
          <label className="text-xs font-semibold text-ink-muted">Tag<input aria-label="Filter by tag" value={tag} onChange={(event) => setTag(event.target.value)} maxLength={40} placeholder="Exact tag name" className="field-input mt-1" /></label>
        </div>}
      </section>

      <div className="mt-5 flex items-center justify-between gap-3"><h3 className="text-xs font-medium text-ink-subtle">{feed.isPending ? "Loading memory…" : `${records.length}${feed.hasNextPage ? "+" : ""} ${records.length === 1 ? "memory" : "memories"}`}</h3>{tag && <span className="text-xs text-ink-muted">Tag: #{tag}</span>}</div>
      {feed.isPending && <div role="status" aria-label="Loading memory" className="mt-3 grid gap-4 sm:grid-cols-2"><div className="h-52 animate-pulse rounded-xl bg-surface" /><div className="h-52 animate-pulse rounded-xl bg-surface" /></div>}
      {feed.isError && !feed.data && <div className="mt-3"><ErrorState title="Memory could not be loaded" message={feed.error.message} onRetry={() => void feed.refetch()} /></div>}
      {feed.isSuccess && records.length === 0 && <div className="mt-3"><EmptyState icon={<BookOpen size={26} />} title={hasFilters ? "No matching memory" : "No memory yet"} action={!hasFilters && <div className="flex flex-wrap justify-center gap-2">{!archived && <Button variant="primary" onClick={() => setParam("new", "1")}><Plus size={16} aria-hidden="true" />Add memory</Button>}<Link to="/help/memory" className={`${buttonBase} ${buttonClasses.secondary}`}>Learn about memory</Link></div>}>{hasFilters ? "Try another search or clear the filters." : <>Memory stores decisions, facts, rules and other knowledge that should survive between AI sessions. Try adding: <em>"Maximum party size is 4."</em></>}</EmptyState></div>}
      {records.length > 0 && <ul className="mt-2 grid gap-3 md:grid-cols-2 2xl:grid-cols-3">{records.map((memory) => <MemoryCard key={memory.id} memory={memory} selected={selected === memory.human_id} onOpen={(record) => setParam("memory", record.human_id)} onTag={setTag} />)}</ul>}
      {feed.isError && feed.data && <div role="alert" className="mt-4 text-sm text-danger-ink">More memory could not be loaded. <button type="button" className="font-semibold underline" onClick={() => void feed.fetchNextPage()}>Try again</button></div>}
      {feed.hasNextPage && <div className="mt-6 text-center"><Button onClick={() => void feed.fetchNextPage()} disabled={feed.isFetchingNextPage}>{feed.isFetchingNextPage ? "Loading more…" : "Load more memory"}</Button></div>}

      {reviewing && <IssueReview projectId={projectId} onClose={() => setReviewing(false)} />}
      {(selected || creating) && <MemoryPanel key={creating ? "new" : selected!} projectId={projectId} memoryRef={creating ? null : selected} defaultTaskRef={taskRef} defaultType={newType} onClose={closePanel} onChanged={memoryChanged} readonly={archived} />}
    </div>
  );
}

import { Activity, ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { Button, EmptyState, ErrorState } from "../ui";
import type { ActivityActor, ActivityEntityType, ActivityEvent, ActivityFilter, ActivityFilters } from "../../types/activity";
import { checkpointPath, memoryPath, projectPath, taskPath } from "../../lib/routes";

const filterOptions: { value: ActivityFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "human", label: "Human" },
  { value: "claude", label: "Claude" },
  { value: "codex", label: "Codex" },
  { value: "tasks", label: "Tasks" },
  { value: "memory", label: "Memory" },
  { value: "git", label: "Git" },
];

const eventLabels: Record<string, string> = {
  PROJECT_CREATED: "Project created",
  PROJECT_UPDATED: "Project updated",
  PROJECT_ARCHIVED: "Project archived",
  PROJECT_RESTORED: "Project restored",
  TASK_CREATED: "Task created",
  TASK_STARTED: "Work started",
  TASK_UPDATED: "Task updated",
  TASK_BLOCKED: "Task blocked",
  TASK_COMPLETED: "Task completed",
  TASK_ARCHIVED: "Task archived",
  MEMORY_CREATED: "Memory created",
  MEMORY_LINKED: "Memories linked",
  MEMORY_UNLINKED: "Memories unlinked",
  MEMORY_UPDATED: "Memory updated",
  MEMORY_LOCKED: "Memory locked",
  MEMORY_SUPERSEDED: "Memory superseded",
  MEMORY_ARCHIVED: "Memory archived",
  MEMORY_INVALIDATED: "Memory marked incorrect",
  CHECKPOINT_CREATED: "Checkpoint recorded",
  GIT_COMMIT_DETECTED: "Git commit detected",
};

function labelForEvent(type: string): string {
  if (eventLabels[type]) return eventLabels[type];
  const words = type.toLowerCase().replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function textField(metadata: Record<string, unknown>, name: string): string | null {
  const value = metadata[name];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function eventDetails(event: ActivityEvent): { reference: string | null; title: string | null; summary: string | null } {
  const metadata = event.metadata ?? {};
  const reference = textField(metadata, "human_id") ?? textField(metadata, "task_human_id") ?? textField(metadata, "commit");
  const title = textField(metadata, "title") ?? textField(metadata, "subject") ?? textField(metadata, "name");
  const summary = textField(metadata, "summary");
  return { reference, title, summary: summary === title ? null : summary };
}

function actorLabel(type: ActivityActor, name: string | null): string {
  const actor = type.charAt(0).toUpperCase() + type.slice(1);
  return name && name.toLowerCase() !== type ? `${name} · ${actor}` : actor;
}

function entityLink(event: ActivityEvent): { to: string; label: string } | null {
  if (event.event_type.endsWith("_DELETED")) return null;
  const project = projectPath(event.project_id);
  const entityId = event.entity_id ?? (event.entity_type === "task" ? event.task_id : null);
  if (!entityId) return null;
  const paths: Partial<Record<ActivityEntityType, { to: string; label: string }>> = {
    project: { to: project, label: "Open project" },
    task: { to: taskPath(event.project_id, entityId), label: "Open task" },
    memory: { to: memoryPath(event.project_id, entityId), label: "Open memory" },
    checkpoint: { to: checkpointPath(event.project_id, entityId), label: "Open checkpoint" },
    git: { to: project, label: "Open project" },
  };
  return event.entity_type ? paths[event.entity_type] ?? null : null;
}

function shortTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const sameYear = date.getFullYear() === new Date().getFullYear();
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: sameYear ? undefined : "numeric", hour: "numeric", minute: "2-digit" }).format(date);
}

function timestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export function filtersForActivity(value: ActivityFilter): ActivityFilters {
  if (value === "human" || value === "claude" || value === "codex") return { actorTypes: [value] };
  if (value === "tasks" || value === "memory" || value === "git") return { entityTypes: [value === "tasks" ? "task" : value] };
  return {};
}

export function ActivityFilterBar({ value, onChange }: { value: ActivityFilter; onChange: (value: ActivityFilter) => void }) {
  return <div role="group" aria-label="Activity filter" className="segmented mb-5">
    {filterOptions.map((option) => <button key={option.value} type="button" aria-pressed={value === option.value} onClick={() => onChange(option.value)} className={`filter-tab ${value === option.value ? "filter-tab-active" : ""}`}>{option.label}</button>)}
  </div>;
}

/** One or two lines per event: the record it touched (linked when it still exists), then what happened, who, and when. */
export function CompactActivityItem({ event }: { event: ActivityEvent }) {
  const details = eventDetails(event);
  const link = entityLink(event);
  const label = labelForEvent(event.event_type);
  const subject = details.reference || details.title
    ? <>{details.reference && <span className="mr-1.5 font-semibold">{details.reference}</span>}{details.title}</>
    : null;
  return <li className="border-t border-line py-2.5 first:border-t-0">
    {subject
      ? link
        ? <Link to={link.to} title={link.label} className="block truncate text-sm font-medium text-forest underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-forest">{subject}</Link>
        : <p className="truncate text-sm font-medium text-ink">{subject}</p>
      : null}
    <p className={`flex flex-wrap items-center gap-x-1.5 text-xs text-ink-muted ${subject ? "mt-0.5" : ""}`}>
      {!subject && link ? <Link to={link.to} className="text-sm font-medium text-forest hover:underline focus-visible:outline-2 focus-visible:outline-forest">{label}</Link> : <span className={subject ? "font-semibold text-ink" : "text-sm font-medium text-ink"}>{label}</span>}
      <span aria-hidden="true">·</span><span>{actorLabel(event.actor_type, event.actor_name)}</span>
      <span aria-hidden="true">·</span><time dateTime={event.timestamp} title={timestamp(event.timestamp)}>{shortTimestamp(event.timestamp)}</time>
    </p>
  </li>;
}

function ActivityItem({ event, workspace }: { event: ActivityEvent; workspace: boolean }) {
  const details = eventDetails(event);
  const link = entityLink(event);
  return <li className="rounded-xl border border-line bg-surface px-4 py-4 shadow-card sm:px-5">
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-muted">
      <span className="rounded-full bg-sage-pale px-2.5 py-1 font-semibold text-forest">{actorLabel(event.actor_type, event.actor_name)}</span>
      <time dateTime={event.timestamp}>{timestamp(event.timestamp)}</time>
    </div>
    <h3 className="mt-2 text-sm font-semibold text-ink">{labelForEvent(event.event_type)}</h3>
    {(details.reference || details.title) && <p className="mt-1 min-w-0 break-words text-sm text-ink-muted">{details.reference && <span className="mr-2 font-semibold text-forest">{details.reference}</span>}{details.title}</p>}
    {details.summary && <p className="mt-1 line-clamp-2 whitespace-pre-line text-sm text-ink-muted">{details.summary}</p>}
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs font-semibold">
      {workspace && <Link to={projectPath(event.project_id)} className="text-ink-muted underline-offset-2 hover:text-forest hover:underline focus-visible:outline-2 focus-visible:outline-forest">{event.project_name}</Link>}
      {link && <Link to={link.to} className="inline-flex items-center gap-0.5 text-forest underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-forest">{link.label}<ChevronRight size={13} aria-hidden="true" /></Link>}
    </div>
  </li>;
}

export function ActivityResults({ events, filter, workspace, isPending, error, hasNextPage, isFetchingNextPage, onRetry, onLoadMore }: {
  events: ActivityEvent[];
  filter: ActivityFilter;
  workspace: boolean;
  isPending: boolean;
  error: string | null;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  onRetry: () => void;
  onLoadMore: () => void;
}) {
  if (isPending) return <div role="status" aria-label="Loading activity" className="h-48 animate-pulse rounded-xl bg-surface" />;
  if (error && events.length === 0) return <ErrorState title="Activity could not be loaded" message={error} onRetry={onRetry} />;
  return <div>
    {events.length === 0 ? <EmptyState icon={<Activity size={26} />} title={filter === "all" ? "No activity yet" : "No matching activity"}>{filter === "all" ? "Changes to tasks, memory, and checkpoints will appear here as they are recorded." : `Try another filter to see more of ${workspace ? "your workspace" : "this project's"} history.`}</EmptyState>
      : <ol aria-label={workspace ? "Workspace activity" : "Project activity"} className="space-y-3">{events.map((event) => <ActivityItem key={event.id} event={event} workspace={workspace} />)}</ol>}
    {error && events.length > 0 && <p role="alert" className="mt-4 text-sm text-danger-ink">More activity could not be loaded. <button type="button" className="font-semibold underline" onClick={onLoadMore}>Try again</button></p>}
    {hasNextPage && !error && <div className="mt-6 text-center"><Button onClick={onLoadMore} disabled={isFetchingNextPage}>{isFetchingNextPage ? "Loading more…" : "Load more activity"}</Button></div>}
  </div>;
}

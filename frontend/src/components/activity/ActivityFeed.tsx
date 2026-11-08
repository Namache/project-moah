import { Activity, BookOpen, ChevronRight, Flag, FolderKanban, GitCommitHorizontal, Library, ListTodo, type LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { Button, EmptyState, ErrorState } from "../ui";
import type { ActivityActor, ActivityEntityType, ActivityEvent, ActivityFilter, ActivityFilters } from "../../types/activity";
import { checkpointPath, memoryPath, projectPath, taskPath } from "../../lib/routes";
import { labels, locale, msg, t } from "../../lib/i18n";

const filterOptions: { value: ActivityFilter; label: string }[] = [
  labels({ value: "all", label: msg("All") }, ["label"]),
  labels({ value: "human", label: msg("You") }, ["label"]),
  labels({ value: "claude", label: "Claude" }, ["label"]),
  labels({ value: "codex", label: "Codex" }, ["label"]),
  labels({ value: "tasks", label: msg("Tasks") }, ["label"]),
  labels({ value: "memory", label: msg("Memory") }, ["label"]),
  labels({ value: "git", label: "Git" }, ["label"]),
];

const eventLabels: Record<string, string> = labels({
  PROJECT_CREATED: msg("Project created"),
  PROJECT_UPDATED: msg("Project updated"),
  PROJECT_ARCHIVED: msg("Project archived"),
  PROJECT_RESTORED: msg("Project restored"),
  TASK_CREATED: msg("Task created"),
  TASK_STARTED: msg("Work started"),
  TASK_UPDATED: msg("Task updated"),
  TASK_BLOCKED: msg("Task blocked"),
  TASK_COMPLETED: msg("Task completed"),
  TASK_ARCHIVED: msg("Task archived"),
  MEMORY_CREATED: msg("Memory created"),
  MEMORY_LINKED: msg("Memories linked"),
  MEMORY_UNLINKED: msg("Memories unlinked"),
  MEMORY_UPDATED: msg("Memory updated"),
  MEMORY_LOCKED: msg("Memory locked"),
  MEMORY_SUPERSEDED: msg("Memory superseded"),
  MEMORY_ARCHIVED: msg("Memory archived"),
  MEMORY_INVALIDATED: msg("Memory marked incorrect"),
  CHECKPOINT_CREATED: msg("Checkpoint recorded"),
  GIT_COMMIT_DETECTED: msg("Git commit detected"),
  CHECKPOINT_UPDATED: msg("Checkpoint updated"),
  COMMIT_LINKED: msg("Commit linked to a task"),
  FILE_CREATED: msg("File notes added"),
  FILE_UPDATED: msg("File notes updated"),
  IMAGE_ATTACHED: msg("Image added"),
  IMAGE_REMOVED: msg("Image removed"),
  LINK_CREATED: msg("Link added"),
  LINK_CONFIRMED: msg("Link confirmed"),
  LINK_REJECTED: msg("Link rejected"),
  LINK_REMOVED: msg("Link removed"),
  LINK_UPDATED: msg("Link updated"),
  MEMORY_DELETED: msg("Memory deleted"),
  MEMORY_RESTORED: msg("Memory restored"),
  MEMORY_UNLOCKED: msg("Memory unlocked"),
  MILESTONE_CREATED: msg("Milestone created"),
  MILESTONE_UPDATED: msg("Milestone updated"),
  MILESTONE_ARCHIVED: msg("Milestone archived"),
  PROPOSAL_CREATED: msg("Suggestion made"),
  PROPOSAL_ACCEPTED: msg("Suggestion accepted"),
  PROPOSAL_REJECTED: msg("Suggestion dismissed"),
  SHELF_CREATED: msg("Shelf created"),
  SHELF_UPDATED: msg("Shelf updated"),
  SHELF_DELETED: msg("Shelf deleted"),
  SHELF_MEMBER_ADDED: msg("Added to a shelf"),
  SHELF_MEMBER_REMOVED: msg("Taken off a shelf"),
  TASK_CRITERION_UPDATED: msg("Requirement updated"),
  TASK_CRITERION_ADDED: msg("Requirement added"),
  TASK_CRITERION_REMOVED: msg("Requirement removed"),
  TASK_DELETED: msg("Task deleted"),
  TASK_MOVED: msg("Task moved"),
  TASK_REOPENED: msg("Task reopened"),
  TASK_FOCUS_SET: msg("Focus set"),
  TASK_FOCUS_CLEARED: msg("Focus cleared"),
  TASK_RELATIONSHIP_ADDED: msg("Task link added"),
  TASK_RELATIONSHIP_REMOVED: msg("Task link removed"),
  FILE_ASSOCIATED: msg("File linked"),
  REVIEW_SUBMITTED: msg("Handed over for review"),
  REVIEW_ACCEPTED: msg("Accepted in Review"),
  REVIEW_REJECTED: msg("Sent back from Review"),
  REVIEW_REOPENED: msg("Reopened after acceptance"),
  REVIEW_FOLLOW_UPS: msg("Follow-up tasks made"),
  QUESTION_ASKED: msg("Question for you"),
  WAIT_UPDATED: msg("Still waiting for you"),
  QUESTION_ANSWERED: msg("Question answered"),
});

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

const actorNames: Record<string, string> = labels({ human: msg("You"), system: msg("System"), claude: "Claude", codex: "Codex" });

function actorLabel(type: ActivityActor, name: string | null): string {
  const actor = actorNames[type] ?? type.charAt(0).toUpperCase() + type.slice(1);
  return name && name.toLowerCase() !== type ? `${name} · ${actor}` : actor;
}

function entityLink(event: ActivityEvent): { to: string; label: string } | null {
  if (event.event_type.endsWith("_DELETED")) return null;
  const project = projectPath(event.project_id);
  const entityId = event.entity_id ?? (event.entity_type === "task" ? event.task_id : null);
  if (!entityId) return null;
  const paths: Partial<Record<ActivityEntityType, { to: string; label: string }>> = {
    project: { to: project, label: t("Open project") },
    task: { to: taskPath(event.project_id, entityId), label: t("Open task") },
    memory: { to: memoryPath(event.project_id, entityId), label: t("Open memory") },
    checkpoint: { to: checkpointPath(event.project_id, entityId), label: t("Open checkpoint") },
    git: { to: project, label: t("Open project") },
  };
  return event.entity_type ? paths[event.entity_type] ?? null : null;
}

function shortTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const sameYear = date.getFullYear() === new Date().getFullYear();
  return new Intl.DateTimeFormat(locale(), { month: "short", day: "numeric", year: sameYear ? undefined : "numeric", hour: "numeric", minute: "2-digit" }).format(date);
}

function timestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(locale(), { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function timeOfDay(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(locale(), { hour: "numeric", minute: "2-digit" }).format(date);
}

/** "Today", "Yesterday", then a date (with the year only when it isn't this year). */
function dayLabel(date: Date): string {
  if (Number.isNaN(date.getTime())) return t("Unknown date");
  const today = new Date();
  const start = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((start(today) - start(date)) / 86_400_000);
  if (days === 0) return t("Today");
  if (days === 1) return t("Yesterday");
  return new Intl.DateTimeFormat(locale(), { weekday: "long", month: "long", day: "numeric", year: date.getFullYear() === today.getFullYear() ? undefined : "numeric" }).format(date);
}

export function filtersForActivity(value: ActivityFilter): ActivityFilters {
  if (value === "human" || value === "claude" || value === "codex") return { actorTypes: [value] };
  if (value === "tasks" || value === "memory" || value === "git") return { entityTypes: [value === "tasks" ? "task" : value] };
  return {};
}

export function ActivityFilterBar({ value, onChange }: { value: ActivityFilter; onChange: (value: ActivityFilter) => void }) {
  return <div role="group" aria-label={t("Activity filter")} className="segmented mb-5">
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

const entityIcons: Record<ActivityEntityType, LucideIcon> = { project: FolderKanban, task: ListTodo, memory: BookOpen, checkpoint: Flag, git: GitCommitHorizontal };

/** One row of the timeline: an icon for what it touched, what happened, the item, then who, where and when. */
function ActivityItem({ event, workspace }: { event: ActivityEvent; workspace: boolean }) {
  const details = eventDetails(event);
  const link = entityLink(event);
  const Icon = event.event_type.startsWith("SHELF_") ? Library : (event.entity_type && entityIcons[event.entity_type]) || Activity;
  const subject = details.reference || details.title
    ? <>{details.reference && <span className="mr-1.5 font-semibold text-forest">{details.reference}</span>}<span className="text-ink">{details.title}</span></>
    : null;
  return <li className="flex gap-3 border-t border-line px-4 py-3 first:border-t-0 sm:px-5">
    <span className="mt-0.5 inline-flex h-7 w-7 flex-none items-center justify-center rounded-full bg-neutral-soft text-ink-muted" aria-hidden="true"><Icon size={14} /></span>
    <div className="min-w-0 flex-1">
      <p className="text-sm">
        <span className="font-semibold text-ink">{labelForEvent(event.event_type)}</span>
        {subject && <>{" "}<span className="text-ink-subtle" aria-hidden="true">·</span>{" "}
          {link ? <Link to={link.to} title={link.label} className="break-words underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-forest">{subject}</Link> : <span className="break-words">{subject}</span>}</>}
        {!subject && link && <>{" "}<Link to={link.to} className="inline-flex items-center gap-0.5 text-xs font-semibold text-forest underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-forest">{link.label}<ChevronRight size={13} aria-hidden="true" /></Link></>}
      </p>
      {details.summary && <p className="mt-0.5 line-clamp-2 whitespace-pre-line text-sm text-ink-muted">{details.summary}</p>}
      <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs text-ink-muted">
        <span>{actorLabel(event.actor_type, event.actor_name)}</span>
        {workspace && <><span aria-hidden="true">·</span><Link to={projectPath(event.project_id)} className="underline-offset-2 hover:text-forest hover:underline focus-visible:outline-2 focus-visible:outline-forest">{event.project_name}</Link></>}
        <span aria-hidden="true">·</span><time dateTime={event.timestamp} title={timestamp(event.timestamp)}>{timeOfDay(event.timestamp)}</time>
      </p>
    </div>
  </li>;
}

/** Events grouped by the local day they happened, newest day first (the feed is already newest first). */
function byDay(events: ActivityEvent[]): { key: string; label: string; events: ActivityEvent[] }[] {
  const groups: { key: string; label: string; events: ActivityEvent[] }[] = [];
  for (const event of events) {
    const date = new Date(event.timestamp);
    const key = `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
    const last = groups[groups.length - 1];
    if (last?.key === key) last.events.push(event);
    else groups.push({ key, label: dayLabel(date), events: [event] });
  }
  return groups;
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
  if (isPending) return <div role="status" aria-label={t("Loading activity")} className="h-48 animate-pulse rounded-xl bg-surface" />;
  if (error && events.length === 0) return <ErrorState title={t("Activity could not be loaded")} message={error} onRetry={onRetry} />;
  return <div>
    {events.length === 0 ? <EmptyState icon={<Activity size={26} />} title={filter === "all" ? t("No activity yet") : t("No matching activity")}>{filter === "all" ? t("Changes to tasks, memory, and checkpoints will appear here as they are recorded.") : workspace ? t("Try another filter to see more of your workspace's history.") : t("Try another filter to see more of this project's history.")}</EmptyState>
      : <div className="space-y-6">
        {byDay(events).map((day) => <section key={day.key} aria-label={day.label}>
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-muted">{day.label}</h2>
          <ol className="overflow-hidden rounded-xl border border-line bg-surface shadow-card">{day.events.map((event) => <ActivityItem key={event.id} event={event} workspace={workspace} />)}</ol>
        </section>)}
      </div>}
    {error && events.length > 0 && <p role="alert" className="mt-4 text-sm text-danger-ink">{t("More activity could not be loaded.")} <button type="button" className="font-semibold underline" onClick={onLoadMore}>{t("Try again")}</button></p>}
    {hasNextPage && !error && <div className="mt-6 text-center"><Button onClick={onLoadMore} disabled={isFetchingNextPage}>{isFetchingNextPage ? t("Loading more…") : t("Load more activity")}</Button></div>}
  </div>;
}

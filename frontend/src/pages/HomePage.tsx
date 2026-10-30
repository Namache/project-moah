import { Activity as ActivityIcon, CheckCircle2, Crosshair, FolderKanban, Inbox, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Onboarding, ONBOARDING_KEY } from "../components/onboarding/Onboarding";
import { EmptyState, ErrorState, ProgressBar, ProjectAvatar, ProjectTile, Widget, buttonBase, buttonClasses, formatDate, toneClasses } from "../components/ui";
import { CompactActivityItem } from "../components/activity/ActivityFeed";
import { useWorkspaceRecent } from "../hooks/useActivity";
import { taskStatusStyle } from "../lib/tones";
import { useLatestCheckpoint } from "../hooks/useCheckpoints";
import { useProjects } from "../hooks/useProjects";
import { usePendingProposals } from "../hooks/useProposals";
import { useOverviews } from "../hooks/useTasks";
import { readPref } from "../lib/prefs";
import { projectPath, taskPath } from "../lib/routes";
import { statusLabels } from "../types/task";
import type { Project } from "../types/project";
import type { ProjectOverview } from "../types/task";
import { locale, t, tp, tx } from "../lib/i18n";

const linkClass = "rounded font-semibold text-forest hover:underline focus-visible:outline-2 focus-visible:outline-forest";

/** "3 hours ago", falling back to the date once it is more than a week old. */
function since(value: string): string {
  const seconds = (new Date(value).getTime() - Date.now()) / 1000;
  if (!Number.isFinite(seconds)) return "";
  const format = new Intl.RelativeTimeFormat(locale(), { numeric: "auto" });
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [["minute", 60], ["hour", 3600], ["day", 86400]];
  if (Math.abs(seconds) < 60) return t("just now");
  if (Math.abs(seconds) > 7 * 86400) return formatDate(value);
  const [unit, size] = [...steps].reverse().find(([, s]) => Math.abs(seconds) >= s)!;
  return format.format(Math.round(seconds / size), unit);
}

function greeting(hour: number): string {
  if (hour < 5) return t("Good night");
  if (hour < 12) return t("Good morning");
  if (hour < 18) return t("Good afternoon");
  return t("Good evening");
}

/** One project's focus task, or a nudge to pick one. */
function FocusRow({ project, overview }: { project: Project; overview: ProjectOverview | undefined }) {
  const focus = overview?.focus_task ?? null;
  if (!focus) {
    return (
      <li className="flex items-center gap-3 py-2.5">
        <ProjectAvatar project={project} size="small" />
        <p className="min-w-0 flex-1 truncate text-sm text-ink-muted">{tx("<b>{name}</b>: nothing in focus", { b: (text) => <span className="font-medium text-ink">{text}</span>, name: project.name })}</p>
        <Link to={projectPath(project.id, "tasks")} className={`${linkClass} flex-none text-sm`}>{t("Pick a task")}<span className="sr-only"> {t("for {name}", { name: project.name })}</span></Link>
      </li>
    );
  }
  const { tone, icon: Icon } = taskStatusStyle[focus.status];
  return (
    <li className="py-1">
      <Link to={taskPath(project.id, focus.human_id)} className="-mx-2 flex items-start gap-3 rounded-lg px-2 py-2 hover:bg-hover focus-visible:outline-2 focus-visible:outline-forest">
        <Icon size={18} className={`mt-0.5 flex-none ${toneClasses[tone].text}`} aria-label={statusLabels[focus.status]} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold text-ink">{focus.title}</span>
          {focus.next_action && <span className="mt-0.5 block truncate text-sm text-ink-muted">{t("Next: {action}", { action: focus.next_action })}</span>}
          <span className="mt-1 flex items-center gap-1.5 text-xs text-ink-subtle"><ProjectAvatar project={project} size="small" />{project.name} · {focus.human_id}</span>
        </span>
      </Link>
    </li>
  );
}

/** A coloured tile per project: the quickest way in. */
function ProjectTileLink({ project, overview, pending }: { project: Project; overview: ProjectOverview | undefined; pending: number }) {
  const checkpoint = useLatestCheckpoint(project.id).data;
  const milestone = overview?.active_milestone ?? null;
  const percent = milestone?.task_count ? Math.round((milestone.completed_task_count / milestone.task_count) * 100) : null;
  return (
    <li className="min-w-0">
      <Link to={projectPath(project.id)} className="group block rounded-xl p-1.5 hover:bg-hover focus-visible:outline-2 focus-visible:outline-forest">
        <span className="relative block">
          <ProjectTile project={project} className="transition-transform group-hover:-translate-y-0.5" />
          {pending > 0 && <span className="absolute -right-1.5 -top-1.5 min-w-6 rounded-full border-2 border-surface bg-primary px-1.5 text-center text-xs font-semibold leading-5 text-white" aria-label={t("{count} in Inbox", { count: pending })}>{pending}</span>}
        </span>
        <span className="mt-2.5 block truncate text-center text-sm font-semibold text-ink">{project.name}</span>
        <span className="mt-0.5 block truncate text-center text-xs text-ink-subtle">
          {checkpoint?.id ? t("Saved {when}", { when: since(checkpoint.created_at) }) : milestone ? milestone.name : t("No milestone")}
        </span>
        {percent !== null && <span className="mx-auto mt-2 block w-3/4"><ProgressBar value={percent} label={t("{project}: {share} of {milestone} done", { project: project.name, share: `${percent}%`, milestone: milestone!.name })} /></span>}
      </Link>
    </li>
  );
}

export function HomePage() {
  const projects = useProjects();
  const overviews = useOverviews();
  const [params] = useSearchParams();
  const [guideClosed, setGuideClosed] = useState(false);
  const pending = usePendingProposals().data;
  const recent = useWorkspaceRecent();

  // Decide once, when the project list first loads, so creating a project inside the guide
  // cannot make the guide vanish halfway through.
  const [guideWanted, setGuideWanted] = useState<boolean | null>(null);
  useEffect(() => {
    if (guideWanted === null && projects.isSuccess) setGuideWanted(projects.data.length === 0 && readPref(ONBOARDING_KEY) !== "1");
  }, [guideWanted, projects.isSuccess, projects.data]);
  const showGuide = !guideClosed && (params.get("tour") === "1" || guideWanted === true);
  if (showGuide) return <div className="py-6"><Onboarding onDone={() => setGuideClosed(true)} /></div>;

  const active = (projects.data ?? [])
    .filter((project) => project.status === "active")
    .sort((a, b) => (b.last_opened_at ?? b.updated_at).localeCompare(a.last_opened_at ?? a.updated_at));
  const others = (projects.data ?? []).filter((project) => project.status === "paused" || project.status === "completed").length;
  const overviewById = new Map((overviews.data ?? []).map((o) => [o.project_id, o]));
  const waiting = pending?.total ?? 0;

  const now = new Date();
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{greeting(now.getHours())}</h1>
        <p className="text-xs font-semibold uppercase tracking-wider text-ink-subtle">{now.toLocaleDateString(locale(), { weekday: "long", day: "numeric", month: "long", year: "numeric" })}</p>
      </header>

      {projects.isPending ? <div role="status" aria-label={t("Loading projects")} className="grid gap-4 lg:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="h-48 animate-pulse rounded-xl bg-surface" />)}</div>
        : projects.isError ? <ErrorState title={t("Projects are unavailable")} message={projects.error.message} onRetry={() => void projects.refetch()} />
        : active.length === 0 ? (
          <EmptyState icon={<FolderKanban size={26} />} title={t("No active projects yet")} action={<Link to="/projects?new=1" className={`${buttonBase} ${buttonClasses.primary}`}><Plus size={16} aria-hidden="true" />{t("New project")}</Link>}>
            {t("Create a project, or open a folder in Claude Code or Codex and it shows up here.")}
          </EmptyState>
        ) : (
          <>
            <div className="grid gap-4 lg:grid-cols-3">
              <Widget title={t("In focus")} icon={Crosshair} to="/tasks" linkLabel={t("All tasks")} className="lg:col-span-2">
                <ul className="divide-y divide-line">
                  {active.map((project) => <FocusRow key={project.id} project={project} overview={overviewById.get(project.id)} />)}
                </ul>
              </Widget>

              <div className="grid gap-4">
                <Widget title={t("Inbox")} icon={Inbox} to="/review" linkLabel={t("Open Inbox")}>
                  {waiting > 0
                    ? <Link to="/review" className="flex items-center gap-3 rounded-lg focus-visible:outline-2 focus-visible:outline-forest"><span className="text-4xl font-semibold tabular-nums tracking-tight text-ink">{waiting}</span><span className="text-sm text-ink-muted">{tp(waiting, "suggestion waits for your decision", "suggestions wait for your decision")}</span></Link>
                    : <p className="flex items-center gap-2.5 text-sm text-ink-muted"><CheckCircle2 size={22} className="text-success" aria-hidden="true" />{t("All caught up")}</p>}
                </Widget>
                <Widget title={t("Recent activity")} icon={ActivityIcon} to="/activity" linkLabel={t("All activity")}>
                  {recent.isSuccess && recent.data.length === 0 && <p className="text-sm text-ink-subtle">{t("Nothing yet.")}</p>}
                  {recent.isSuccess && recent.data.length > 0 && <ol className="-mt-2">{recent.data.slice(0, 4).map((event) => <CompactActivityItem key={event.id} event={event} />)}</ol>}
                </Widget>
              </div>
            </div>

            <Widget title={t("Projects")} icon={FolderKanban} to="/projects" linkLabel={t("All projects")}>
              <ul className="grid grid-cols-[repeat(auto-fill,minmax(8.5rem,1fr))] gap-3" aria-label={t("Active projects")}>
                {active.map((project) => <ProjectTileLink key={project.id} project={project} overview={overviewById.get(project.id)} pending={pending?.by_project?.[project.id] ?? 0} />)}
                <li className="min-w-0">
                  <Link to="/projects?new=1" className="group block rounded-xl p-1.5 hover:bg-hover focus-visible:outline-2 focus-visible:outline-forest">
                    <span className="flex aspect-square items-center justify-center rounded-xl border-2 border-dashed border-line-strong text-ink-subtle group-hover:border-forest group-hover:text-forest"><Plus size={30} aria-hidden="true" /></span>
                    <span className="mt-2.5 block text-center text-sm font-medium text-ink-muted">{t("New project")}</span>
                  </Link>
                </li>
              </ul>
              {others > 0 && <p className="mt-3 text-sm text-ink-muted">{tx(tp(others, "{count} paused or completed project is on <link>Projects</link>.", "{count} paused or completed projects are on <link>Projects</link>."), { link: (text) => <Link to="/projects" className={linkClass}>{text}</Link> })}</p>}
            </Widget>
          </>
        )}
    </div>
  );
}

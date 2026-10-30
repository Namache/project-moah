import { ListTodo } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { TaskMeta, TaskStatusBadge } from "../components/tasks/TaskBits";
import { EmptyState, ErrorState, PageHeading, ProjectAvatar, SegmentedControl } from "../components/ui";
import { useWorkspaceTasks } from "../hooks/useTasks";
import type { WorkspaceTask } from "../types/task";
import { projectPath, taskPath } from "../lib/routes";

export function AllTasksPage() {
  const query = useWorkspaceTasks();
  const [filter, setFilter] = useState<"open" | "blocked" | "completed" | "all">("open");
  const matches = (t: WorkspaceTask) => filter === "all" || (filter === "open" ? !["completed"].includes(t.status) : filter === "blocked" ? t.status === "blocked" || t.is_blocked_by_open_dependency : t.status === "completed");
  const groups = new Map<string, WorkspaceTask[]>();
  for (const task of (query.data ?? []).filter(matches)) groups.set(task.project_id, [...(groups.get(task.project_id) ?? []), task]);
  return (
    <div>
      <PageHeading title="All tasks" className="mb-6" />
      <SegmentedControl label="Task filter" value={filter} onChange={setFilter} className="mb-6" options={[{ value: "open", label: "Open" }, { value: "blocked", label: "Blocked" }, { value: "completed", label: "Done" }, { value: "all", label: "All" }]} />
      {query.isPending ? <div role="status" aria-label="Loading tasks" className="h-48 animate-pulse rounded-xl bg-surface" />
        : query.isError ? <ErrorState title="Tasks could not be loaded" message={query.error.message} onRetry={() => void query.refetch()} />
        : groups.size === 0 ? <EmptyState icon={<ListTodo size={26} />} title="Nothing to show">{query.data.length ? "No tasks match this filter." : "Create a task inside a project and it will appear here, grouped under that project."}</EmptyState>
        : <div className="space-y-8">{[...groups.values()].map((tasks) => (
          <section key={tasks[0].project_id} aria-label={tasks[0].project_name}>
            <Link to={projectPath(tasks[0].project_id, "tasks")} className="mb-3 flex items-center gap-3 rounded-xl text-ink hover:text-forest"><ProjectAvatar project={{ name: tasks[0].project_name, icon: tasks[0].project_icon, accent: tasks[0].project_accent }} /><h2 className="text-base font-semibold tracking-tight">{tasks[0].project_name}</h2></Link>
            <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">{tasks.map((t) => <li key={t.id}><Link to={taskPath(t.project_id, t.human_id)} className="flex items-start gap-4 px-4 py-3 hover:bg-hover focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-forest"><span className="w-20 shrink-0 pt-0.5 text-xs font-medium tabular-nums text-ink-subtle">{t.human_id}</span><span className="min-w-0 flex-1"><span className="block text-sm font-semibold text-ink">{t.title}</span><TaskMeta task={t} /></span><span className="shrink-0"><TaskStatusBadge status={t.status} /></span></Link></li>)}</ul>
          </section>))}</div>}
    </div>
  );
}

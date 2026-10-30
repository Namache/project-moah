import { useCallback, useEffect, useMemo, useState } from "react";
import { LayoutGrid, List, ListTodo, Plus } from "lucide-react";
import { Link } from "react-router-dom";
import { useUrlParams } from "../hooks/useUrlParams";
import { Button, EmptyState, ErrorState, SegmentedControl, buttonBase, buttonClasses } from "../components/ui";
import { NewTaskDialog } from "../components/tasks/NewTaskDialog";
import { ArchivedTasks } from "../components/tasks/ArchivedTasks";
import { MilestoneManager } from "../components/tasks/MilestoneManager";
import { TaskBoard } from "../components/tasks/TaskBoard";
import { TaskList } from "../components/tasks/TaskList";
import { TaskPanel } from "../components/tasks/TaskPanel";
import { useMilestones, useMoveTask, useTasks } from "../hooks/useTasks";
import type { TaskDetail, TaskStatus, TaskSummary } from "../types/task";

function view(): "board" | "list" {
  try { return localStorage.getItem("pb-task-view") === "list" ? "list" : "board"; } catch { return "board"; }
}

export function TasksPage({ projectId, archived }: { projectId: string; archived: boolean }) {
  const [params, updateParams] = useUrlParams();
  const [mode, setMode] = useState(view);
  // false, or the board column a new task starts in.
  const [creating, setCreating] = useState<false | TaskStatus>(false);
  const [managingMilestones, setManagingMilestones] = useState(false);
  const milestoneFilter = params.get("milestone") ?? "";
  const selected = params.get("task");
  const tasksQuery = useTasks(projectId);
  const milestonesQuery = useMilestones(projectId, true);
  const milestones = milestonesQuery.data ?? [];
  const activeMilestones = milestones.filter((milestone) => milestone.status !== "archived");
  const move = useMoveTask(projectId);

  const tasks = useMemo(() => (tasksQuery.data ?? []).filter((t) => !milestoneFilter || t.milestone_id === milestoneFilter), [tasksQuery.data, milestoneFilter]);
  const setParam = useCallback((key: string, value: string | null) => updateParams({ [key]: value }), [updateParams]);
  useEffect(() => {
    if (milestonesQuery.isSuccess && milestoneFilter && !activeMilestones.some((milestone) => milestone.id === milestoneFilter)) setParam("milestone", null);
  }, [milestonesQuery.isSuccess, milestoneFilter, activeMilestones, setParam]);
  // "+ New" in the sidebar arrives with ?new=1.
  const wantsNew = params.get("new") === "1";
  useEffect(() => {
    if (!wantsNew) return;
    if (!archived) setCreating("todo");
    setParam("new", null);
  }, [wantsNew, archived, setParam]);
  const open = (task: TaskSummary) => setParam("task", task.human_id);
  const syncRef = useCallback((task: TaskDetail | null) => setParam("task", task?.human_id ?? null), [setParam]);
  const switchMode = (next: "board" | "list") => { setMode(next); try { localStorage.setItem("pb-task-view", next); } catch { /* optional */ } };

  if (tasksQuery.isError) return <ErrorState title="Tasks could not be loaded" message={tasksQuery.error.message} onRetry={() => void tasksQuery.refetch()} />;
  const empty = tasksQuery.isSuccess && (tasksQuery.data?.length ?? 0) === 0;

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <SegmentedControl label="Task view" value={mode} onChange={switchMode} options={[{ value: "board", label: "Board", icon: LayoutGrid }, { value: "list", label: "List", icon: List }]} />
          <label className="sr-only" htmlFor="milestone-filter">Milestone</label>
          <select id="milestone-filter" value={milestoneFilter} onChange={(e) => setParam("milestone", e.target.value || null)} className="field-input !min-h-9 !w-auto !py-1">
            <option value="">All milestones</option>
            {activeMilestones.map((m) => <option key={m.id} value={m.id}>{m.name} ({m.completed_task_count}/{m.task_count})</option>)}
          </select>
          <Button variant="quiet" aria-expanded={managingMilestones} onClick={() => setManagingMilestones((current) => !current)}>{managingMilestones ? "Hide milestones" : "Manage milestones"}</Button>
        </div>
        {!archived && <Button variant="primary" onClick={() => setCreating("todo")}><Plus size={16} aria-hidden="true" />New task</Button>}
      </div>
      {managingMilestones && (milestonesQuery.isPending ? <p role="status" className="mb-5 text-sm text-ink-muted">Loading milestones…</p> : milestonesQuery.isError ? <div className="mb-5"><ErrorState title="Milestones could not be loaded" message={milestonesQuery.error.message} onRetry={() => void milestonesQuery.refetch()} /></div> : <MilestoneManager projectId={projectId} milestones={milestones} readonly={archived} />)}
      {move.isError && <div className="mb-4"><ErrorState title="That move did not save" message={move.error.message} /></div>}

      {tasksQuery.isPending ? <div role="status" aria-label="Loading tasks" className="h-64 animate-pulse rounded-xl bg-surface" />
        : empty ? <EmptyState icon={<ListTodo size={26} />} title="No tasks yet" action={<div className="flex flex-wrap justify-center gap-2">{!archived && <Button variant="primary" onClick={() => setCreating("todo")}><Plus size={16} />Create first task</Button>}<Link to="/help/tasks" className={`${buttonBase} ${buttonClasses.secondary}`}>Learn about tasks</Link></div>}>Tasks keep you and your AI agents aligned on what needs to be built. Try something small, such as "Implement save migration".</EmptyState>
        : mode === "board" ? <TaskBoard tasks={tasks} selectedId={tasksQuery.data.find((t) => t.human_id === selected)?.id ?? null} onOpen={open} onMove={(id, status, index) => { if (!archived) move.mutate({ id, status, index }); }} onAdd={setCreating} readOnly={archived} />
        : <TaskList tasks={tasks} selectedId={tasksQuery.data.find((t) => t.human_id === selected)?.id ?? null} onOpen={open} />}

      <ArchivedTasks projectId={projectId} onOpen={open} />

      {selected && <TaskPanel key={selected} projectId={projectId} projectArchived={archived} taskRef={selected} onClose={() => updateParams({ task: null, checkpoint: null })} onChanged={syncRef} />}
      {creating && <NewTaskDialog projectId={projectId} defaultStatus={creating} defaultMilestone={milestoneFilter} onClose={() => setCreating(false)} onCreated={(task) => { setCreating(false); setParam("task", task.human_id); }} />}
    </div>
  );
}

import { Link } from "react-router-dom";
import { ListChecks, Play, Target } from "lucide-react";
import { Button, buttonBase, buttonClasses } from "../ui";
import { useFocus } from "../../hooks/useTasks";
import type { TaskSummary } from "../../types/task";
import { HandoffButton } from "../handoff/HandoffButton";
import { WorkOnTaskButton } from "./WorkOnTaskButton";
import { Progress } from "./TaskBits";
import { projectPath, taskPath } from "../../lib/routes";

export function FocusCard({ projectId, task }: { projectId: string; task: TaskSummary | null }) {
  const focus = useFocus(projectId);
  return (
    <section className="rounded-xl border border-line bg-surface p-5 shadow-card sm:p-6" aria-labelledby="focus-title">
      <div className="flex min-h-9 items-center justify-between gap-2">
        <p className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-forest"><Target size={15} aria-hidden="true" />Current focus</p>
        {task && <Button variant="quiet" size="sm" onClick={() => focus.mutate(null)} disabled={focus.isPending} title="Stop pointing agents at this task">Clear focus</Button>}
      </div>
      {task ? (
        <>
          <h2 id="focus-title" className="mt-2 text-xl font-semibold tracking-tight"><span className="text-forest">{task.human_id}</span> {task.title}</h2>
          <div className="mt-3"><Progress done={task.criteria_completed} total={task.criteria_total} label="Requirements complete" /></div>
          {task.next_action && <p className="mt-4 text-sm leading-6 text-ink-muted"><strong className="text-ink">Next:</strong> {task.next_action}</p>}
          <div className="mt-6 flex flex-wrap items-start gap-2">
            <Link to={taskPath(projectId, task.human_id)} className={`${buttonBase} ${buttonClasses.primary}`}><Play size={16} aria-hidden="true" />Continue work</Link>
            <WorkOnTaskButton projectId={projectId} task={task.human_id} compact variant="secondary" />
            <HandoffButton projectId={projectId} task={task.human_id} variant="quiet" />
          </div>
        </>
      ) : (
        <>
          <h2 id="focus-title" className="mt-2 text-xl font-semibold tracking-tight">Nothing in focus yet</h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-ink-muted">Pick the task you are working on. Agents will start from it when they ask what to continue.</p>
          <Link to={projectPath(projectId, "tasks")} className={`${buttonBase} ${buttonClasses.secondary} mt-6`}><ListChecks size={16} aria-hidden="true" />Choose a task</Link>
        </>
      )}
      {focus.isError && <p role="alert" className="mt-3 text-sm text-danger-ink">{focus.error.message}</p>}
    </section>
  );
}

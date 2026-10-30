import type { TaskSummary } from "../../types/task";
import { boardColumns } from "../../types/task";
import { FocusMark, TaskMeta } from "./TaskBits";
import { taskStatusStyle } from "../../lib/tones";
import { toneClasses } from "../ui";

export function TaskRow({ task, onOpen, selected }: { task: TaskSummary; onOpen: (task: TaskSummary) => void; selected?: boolean }) {
  return (
    <li>
      <button type="button" onClick={() => onOpen(task)} aria-pressed={selected} className={`flex w-full items-start gap-4 px-4 py-3 text-left hover:bg-hover focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-forest ${selected ? "bg-sage-pale" : ""}`}>
        <span className="w-20 shrink-0 pt-0.5 text-xs font-bold tracking-wide text-forest">{task.human_id}</span>
        <span className="min-w-0 flex-1"><span className="block text-sm font-semibold text-ink">{task.title}</span><TaskMeta task={task} /></span>
        {task.is_focus && <FocusMark />}
      </button>
    </li>
  );
}

export function TaskList({ tasks, selectedId, onOpen }: { tasks: TaskSummary[]; selectedId: string | null; onOpen: (task: TaskSummary) => void }) {
  return (
    <div className="space-y-5">
      {boardColumns.map(({ status, label }) => {
        const group = tasks.filter((t) => t.status === status).sort((a, b) => a.sort_order - b.sort_order);
        if (!group.length) return null;
        const { tone, icon: Icon } = taskStatusStyle[status];
        return (
          <section key={status} aria-label={label}>
            <h2 className={`mb-2 flex items-center gap-1.5 px-1 text-sm font-semibold ${toneClasses[tone].text}`}><Icon size={15} aria-hidden="true" />{label} <span className="font-normal text-ink-subtle">{group.length}</span></h2>
            <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">{group.map((t) => <TaskRow key={t.id} task={t} onOpen={onOpen} selected={t.id === selectedId} />)}</ul>
          </section>
        );
      })}
    </div>
  );
}

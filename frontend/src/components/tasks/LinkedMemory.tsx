import { BookOpen, Plus } from "lucide-react";
import { Link } from "react-router-dom";
import { useMemoryList } from "../../hooks/useMemory";
import { memoryTypes, type MemoryType } from "../../types/memory";
import { memoryPath, projectPath } from "../../lib/routes";

const typeAccent: Record<MemoryType, string> = {
  decision: "border-l-forest",
  rule: "border-l-special",
  fact: "border-l-info",
  idea: "border-l-warning",
  bug: "border-l-danger",
  note: "border-l-line-strong",
  warning: "border-l-warning",
};

const typeLabel = Object.fromEntries(memoryTypes.map(({ value, label }) => [value, label])) as Record<MemoryType, string>;

export function LinkedMemory({ projectId, task, readOnly = false }: { projectId: string; task: { id: string; human_id: string }; readOnly?: boolean }) {
  const query = useMemoryList(projectId, { task: task.id, statuses: ["active"] });
  const forTask = projectPath(projectId, "memory", { task: task.human_id });

  return (
    <div>
      {query.isPending && <p role="status" className="text-sm text-ink-muted">Loading linked memory…</p>}
      {query.isError && (
        <div role="alert" className="text-sm text-danger-ink">
          <p>Linked memory could not be loaded: {query.error.message}</p>
          <button type="button" onClick={() => void query.refetch()} className="mt-1 font-semibold underline">Try again</button>
        </div>
      )}
      {query.isSuccess && (
        query.data.length > 0 ? (
          <ul className="space-y-2">
            {query.data.map((record) => (
              <li key={record.id}>
                <Link
                  to={memoryPath(projectId, record.human_id)}
                  aria-label={`Open ${typeLabel[record.type]} memory ${record.human_id}: ${record.title}`}
                  className={`block rounded-xl border border-line border-l-4 bg-neutral-soft px-3 py-2.5 hover:bg-sage-pale focus-visible:outline-2 focus-visible:outline-forest ${typeAccent[record.type]}`}
                >
                  <span className="flex items-center gap-2 text-xs text-ink-muted"><BookOpen size={13} aria-hidden="true" /><span className="font-semibold">{typeLabel[record.type]}</span><span aria-hidden="true">·</span><span>{record.human_id}</span></span>
                  <span className="mt-1 block text-sm font-medium text-ink">{record.title}</span>
                </Link>
              </li>
            ))}
          </ul>
        ) : <p className="text-sm text-ink-subtle">No active memory is linked to this task yet.</p>
      )}
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-sm font-medium">
        <Link to={forTask} className="text-forest underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-forest">View task memory</Link>
        {!readOnly && <Link to={projectPath(projectId, "memory", { task: task.human_id, new: "1" })} className="inline-flex items-center gap-1 text-forest underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-forest"><Plus size={14} aria-hidden="true" />Add memory</Link>}
      </div>
    </div>
  );
}

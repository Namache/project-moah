import { useState } from "react";
import { Archive, ChevronDown } from "lucide-react";
import { useArchivedTasks } from "../../hooks/useTasks";
import type { TaskSummary } from "../../types/task";
import { TaskRow } from "./TaskList";
import { t } from "../../lib/i18n";

export function ArchivedTasks({ projectId, onOpen }: { projectId: string; onOpen: (task: TaskSummary) => void }) {
  const [expanded, setExpanded] = useState(false);
  const query = useArchivedTasks(projectId, expanded);

  return (
    <section aria-label={t("Archived tasks")} className="mt-8 border-t border-line pt-5">
      <button type="button" aria-expanded={expanded} aria-controls="archived-tasks-content" onClick={() => setExpanded((value) => !value)} className="flex w-full items-center gap-2 rounded-lg px-1 py-2 text-left text-sm font-semibold text-ink-muted hover:text-forest focus-visible:outline-2 focus-visible:outline-forest">
        <Archive size={16} aria-hidden="true" />
        {t("Archived tasks")}
        {query.data && <span className="font-normal text-ink-subtle">{query.data.length}</span>}
        <ChevronDown size={16} aria-hidden="true" className={`ml-auto transition-transform ${expanded ? "rotate-180" : ""}`} />
      </button>
      {expanded && (
        <div id="archived-tasks-content" className="pt-2">
          {query.isPending && <p role="status" className="text-sm text-ink-subtle">{t("Loading archived tasks…")}</p>}
          {query.isError && <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-danger-ink">{t("Archived tasks could not be loaded:")} {query.error.message}<button type="button" onClick={() => void query.refetch()} className="font-semibold underline">{t("Try again")}</button></div>}
          {query.isSuccess && query.data.length === 0 && <p className="text-sm text-ink-subtle">{t("No archived tasks.")}</p>}
          {query.isSuccess && query.data.length > 0 && (
            <>
              <p className="mb-3 text-xs text-ink-subtle">{t("Open a task to restore it from its details.")}</p>
              <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">{query.data.map((task) => <TaskRow key={task.id} task={task} onOpen={onOpen} />)}</ul>
            </>
          )}
        </div>
      )}
    </section>
  );
}

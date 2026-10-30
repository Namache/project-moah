import { useState } from "react";
import { Link } from "react-router-dom";
import { useUrlParams } from "../../hooks/useUrlParams";
import { Plus } from "lucide-react";
import { Button, ErrorState } from "../ui";
import { useCheckpointsFeed, useLatestCheckpoint } from "../../hooks/useCheckpoints";
import type { Checkpoint } from "../../types/checkpoint";
import { CheckpointPanel } from "./CheckpointPanel";
import { taskPath } from "../../lib/routes";

function checkpointDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }).format(date);
}

function CheckpointCard({ checkpoint, latest, projectId, onOpen }: { checkpoint: Checkpoint; latest: boolean; projectId: string; onOpen: (id: string) => void }) {
  return <article className={`rounded-xl border p-4 ${latest ? "border-forest/40 bg-sage-pale/50" : "border-line bg-surface"}`}>
    <button type="button" onClick={() => onOpen(checkpoint.id)} className="block w-full rounded-lg text-left focus-visible:outline-2 focus-visible:outline-forest" aria-label={`Open checkpoint ${checkpoint.title}`}>
      <span className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <span className="min-w-0 text-sm font-semibold text-ink">{checkpoint.title}</span>
        <span className="shrink-0 text-xs text-ink-subtle">{checkpointDate(checkpoint.created_at)}</span>
      </span>
      {checkpoint.summary && <span className="mt-2 block whitespace-pre-wrap text-sm leading-6 text-ink-muted">{checkpoint.summary}</span>}
      {!checkpoint.summary && checkpoint.next_steps && <span className="mt-2 block whitespace-pre-wrap text-sm leading-6 text-ink-muted">Next: {checkpoint.next_steps}</span>}
    </button>
    {checkpoint.task && <Link to={taskPath(projectId, checkpoint.task.human_id)} className="mt-2 inline-block rounded text-xs font-semibold text-forest hover:underline focus-visible:outline-2 focus-visible:outline-forest">{checkpoint.task.human_id} · {checkpoint.task.title}</Link>}
  </article>;
}

function CheckpointsSection({ projectId, taskId, archived, compact }: { projectId: string; taskId?: string; archived: boolean; compact: boolean }) {
  const [params, updateParams] = useUrlParams();
  const [creating, setCreating] = useState(false);
  const selectedId = params.get("checkpoint");
  const latestQuery = useLatestCheckpoint(projectId, taskId);
  const feedQuery = useCheckpointsFeed(projectId, taskId);
  const records = feedQuery.data?.pages.flat() ?? [];
  const history = records.filter((checkpoint) => checkpoint.id !== latestQuery.data?.id);

  function select(id: string | null) {
    setCreating(false);
    updateParams({ checkpoint: id });
  }

  return <section aria-labelledby={compact ? "task-checkpoints-title" : "project-checkpoints-title"} className={compact ? "border-t border-line px-6 py-5" : "rounded-xl border border-line bg-surface p-5 shadow-card sm:p-6"}>
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 id={compact ? "task-checkpoints-title" : "project-checkpoints-title"} className={compact ? "text-sm font-semibold text-ink" : "text-base font-semibold tracking-tight text-ink"}>Checkpoints</h2>
        <p className="mt-1 text-xs text-ink-subtle">{compact ? "Progress snapshots for this task." : "Progress snapshots that help you resume work."}</p>
      </div>
      {!archived && <Button variant="secondary" onClick={() => { if (selectedId) select(null); setCreating(true); }}><Plus size={16} aria-hidden="true" />Create checkpoint</Button>}
    </div>

    {latestQuery.isPending && <p role="status" className="mt-5 text-sm text-ink-muted">Loading latest checkpoint…</p>}
    {latestQuery.isError && <div className="mt-5"><ErrorState title="Latest checkpoint could not be loaded" message={latestQuery.error.message} onRetry={() => void latestQuery.refetch()} /></div>}
    {latestQuery.isSuccess && <div className="mt-5">
      <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-forest">Latest checkpoint</h3>
      {latestQuery.data
        ? <CheckpointCard checkpoint={latestQuery.data} latest projectId={projectId} onOpen={select} />
        : <div className="rounded-xl border border-dashed border-line bg-neutral-soft px-4 py-5 text-sm text-ink-muted">No checkpoint yet. Record what is done, what remains, and the next step.</div>}
    </div>}

    {feedQuery.isPending && <p role="status" className="mt-5 text-sm text-ink-muted">Loading checkpoint history…</p>}
    {feedQuery.isError && <div className="mt-5"><ErrorState title="Checkpoint history could not be loaded" message={feedQuery.error.message} onRetry={() => void feedQuery.refetch()} /></div>}
    {feedQuery.isSuccess && history.length > 0 && <div className="mt-6">
      <h3 className="mb-3 text-xs font-bold uppercase tracking-wide text-ink-muted">Earlier checkpoints</h3>
      <div className="space-y-2">{history.map((checkpoint) => <CheckpointCard key={checkpoint.id} checkpoint={checkpoint} latest={false} projectId={projectId} onOpen={select} />)}</div>
    </div>}
    {feedQuery.hasNextPage && <Button className="mt-4" onClick={() => void feedQuery.fetchNextPage()} disabled={feedQuery.isFetchingNextPage}>{feedQuery.isFetchingNextPage ? "Loading…" : "Load more checkpoints"}</Button>}

    {(creating || selectedId) && <CheckpointPanel key={creating ? "new" : selectedId ?? ""} projectId={projectId} checkpointId={creating ? null : selectedId} defaultTaskId={taskId} readonly={archived} onClose={() => select(null)} onChanged={select} />}
  </section>;
}

export function ProjectCheckpoints({ projectId, archived }: { projectId: string; archived: boolean }) {
  return <CheckpointsSection projectId={projectId} archived={archived} compact={false} />;
}

export function TaskCheckpoints({ projectId, taskId, archived = false }: { projectId: string; taskId: string; archived?: boolean }) {
  return <CheckpointsSection projectId={projectId} taskId={taskId} archived={archived} compact />;
}
